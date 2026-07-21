from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.ai.models import ChatMessage

from .models import (
    MemoryKnowledgeItem,
    MemorySearchDocument,
    MemorySource,
)
from .knowledge_files import read_knowledge_item_file, rebuild_knowledge_index, write_knowledge_item_file
from .policies import can_write_organization_memory, can_write_personal_memory
from .secret_backends import get_secret_backend
from .security import scan_for_secrets
from .services import MemoryQueueJobKind, enqueue_memory_queue_task
from .vector_backends import MemoryIndexRecord
from .vector_backends import LANCEDB_VECTOR_SCHEMA_VERSION, get_default_fulltext_schema_version
from .vector_backends import get_default_backend
from .vector_backends import get_default_vector_backend


CHAT_MEMORY_PERSONAL_SOURCE = "ai_chat_personal"
CHAT_MEMORY_ORG_SOURCE = "ai_chat_organization"
CHAT_MEMORY_SCHEMA_VERSION = "chat-memory-v1"
CHAT_MEMORY_EXTRACTOR_VERSION = "chat-memory-mvp-v1"

TARGET_SCOPE_PERSONAL = "personal"
TARGET_SCOPE_ORGANIZATION = "organization"


@dataclass(frozen=True)
class SanitizedMemoryText:
    text: str
    secret_handles: tuple[dict, ...]


def remember_knowledge(*, actor, session, payload, request_id=""):
    """Synchronous ``memory.remember`` write path (ADR-0030 decision 2).

    Writes the knowledge file and its git commit under the packet-01
    cross-platform lock, then indexes inline, all within one call. There is no
    queue status in the result: the file write + commit is durable by the time
    this function returns. If inline indexing fails, the write itself still
    succeeds; a retryable ``reindex`` task is enqueued on the unified memory
    queue (``MemoryExternalConnectorJob``) so indexing catches up, with a
    dead-letter path once retries are exhausted.
    """
    _assert_authenticated(actor)
    target_scope = _normalize_target_scope(payload.get("target_scope"))
    if target_scope == TARGET_SCOPE_PERSONAL:
        if not can_write_personal_memory(actor, actor):
            raise PermissionDenied("Personal memory write is not allowed.")
    elif target_scope == TARGET_SCOPE_ORGANIZATION:
        if not can_write_organization_memory(actor):
            raise PermissionDenied("Organization memory write is not allowed for this user.")

    message_ids = _normalize_message_ids(payload.get("message_ids"))
    if not message_ids:
        latest = session.messages.filter(role=ChatMessage.Role.USER).order_by("-created_at", "-id").first()
        if latest:
            message_ids = [latest.id]
    user_note = str(payload.get("user_note", "") or "")
    if not message_ids and not user_note.strip():
        raise ValidationError("message_ids or user_note is required.")
    importance = str(payload.get("importance", "") or "")

    # DEBT(ADR-0030-5a): fail-safe observation-vs-knowledge routing goes here.
    # In stage 5a an utterance that matches the schema of a registered dataset
    # is captured into the data store (apps.memory.data_store.capture) instead
    # of a knowledge file. Until then every remember is a knowledge file (the
    # wiki is the staging area) — the current behavior below.
    knowledge_item, file_result, sanitized = _write_knowledge_item_and_file(
        actor=actor,
        session=session,
        target_scope=target_scope,
        message_ids=message_ids,
        user_note=user_note,
        importance=importance,
    )

    index_status = "ready"
    try:
        index_knowledge_item(knowledge_item)
    except Exception as exc:
        knowledge_item.refresh_from_db(fields=["index_status"])
        index_status = knowledge_item.index_status
        enqueue_memory_queue_task(
            job_kind=MemoryQueueJobKind.REINDEX,
            source_code=knowledge_item.source_code,
            idempotency_key=f"reindex:{knowledge_item.memory_id}",
            payload={"memory_id": knowledge_item.memory_id, "reason": str(exc)},
            request_id=request_id,
        )

    return {
        "memory_id": knowledge_item.memory_id,
        "target_scope": target_scope,
        "knowledge_file_path": file_result.relative_path,
        "knowledge_file_commit": file_result.commit_hash,
        "secret_handles": list(sanitized.secret_handles),
        "index_status": index_status,
        "message": "Memory knowledge item saved.",
    }


@transaction.atomic
def _write_knowledge_item_and_file(*, actor, session, target_scope, message_ids, user_note, importance):
    source_messages = _load_messages(session=session, message_ids=message_ids)
    raw_text = _build_raw_memory_text(messages=source_messages, user_note=user_note)
    if not raw_text.strip():
        raise ValidationError("Memory request has no text to ingest.")

    sanitized = sanitize_memory_text(
        raw_text,
        actor=actor,
        scope=target_scope,
        source_metadata={"actor_id": actor.id, "session_id": getattr(session, "id", None)},
    )
    knowledge_item = create_knowledge_item_for_remember(
        actor=actor,
        session=session,
        target_scope=target_scope,
        message_ids=message_ids,
        user_note=user_note,
        importance=importance,
        safe_text=sanitized.text,
        messages=source_messages,
        secret_handles=sanitized.secret_handles,
    )
    file_result = write_knowledge_item_file(
        knowledge_item,
        body=_normalize_memory_text(sanitized.text),
        commit_message=f"Remember knowledge {knowledge_item.memory_id}",
    )
    rebuild_memory_projection(scope=knowledge_item.scope, owner_user=knowledge_item.owner_user)
    return knowledge_item, file_result, sanitized


def sanitize_memory_text(text: str, *, actor, scope: str, source_metadata=None) -> SanitizedMemoryText:
    value = text or ""
    scan = scan_for_secrets(value)
    if not scan.findings:
        return SanitizedMemoryText(text=value, secret_handles=())

    backend = get_secret_backend()
    replacements = []
    handles = []
    for index, finding in enumerate(scan.findings, start=1):
        ref = backend.create_secret(
            actor=actor,
            label=f"{finding.finding_type} from chat memory",
            metadata={
                **(source_metadata or {}),
                "finding_type": finding.finding_type,
                "reason": finding.reason,
                "confidence": finding.confidence,
                "span_hash": _sha256(value[finding.start : finding.end]),
            },
            scope=scope,
        )
        placeholder = f"<SECRET_HANDLE:{ref.handle}>"
        replacements.append((finding.start, finding.end, placeholder))
        handles.append(
            {
                "handle": ref.handle,
                "provider": ref.provider,
                "url": ref.url,
                "label": f"{finding.finding_type} #{index}",
                "finding_type": finding.finding_type,
            }
        )

    output = []
    cursor = 0
    for start, end, placeholder in sorted(replacements, key=lambda item: item[0]):
        output.append(value[cursor:start])
        output.append(placeholder)
        cursor = end
    output.append(value[cursor:])
    return SanitizedMemoryText(text="".join(output), secret_handles=tuple(handles))


def create_knowledge_item_for_remember(
    *,
    actor,
    session,
    target_scope: str,
    message_ids: list[int],
    user_note: str,
    importance: str,
    safe_text: str,
    messages=(),
    secret_handles=(),
):
    text = _normalize_memory_text(safe_text)
    if not text:
        raise ValidationError("Memory text is empty after sanitization.")
    text_hash = _sha256(text)
    source_hash = _source_content_hash(messages=messages, user_note=user_note)
    scope = (
        MemoryKnowledgeItem.Scope.ORGANIZATION
        if target_scope == TARGET_SCOPE_ORGANIZATION
        else MemoryKnowledgeItem.Scope.PERSONAL
    )
    owner_user = actor if scope == MemoryKnowledgeItem.Scope.PERSONAL else None
    memory_id = _memory_id(scope=scope, owner_user=owner_user, text_hash=text_hash)
    source_refs = _source_refs_for_remember(session=session, message_ids=message_ids)
    defaults = {
        "scope": scope,
        "owner_user": owner_user,
        "kind": MemoryKnowledgeItem.Kind.SECRET_REFERENCE if secret_handles else MemoryKnowledgeItem.Kind.FACT,
        "text_hash": text_hash,
        "sensitivity": "internal" if not secret_handles else "confidential",
        "scope_tokens": _scope_tokens_for_memory(scope=scope, owner_user=owner_user),
        "status": MemoryKnowledgeItem.Status.ACTIVE,
        "source_session": session,
        "source_message_ids": list(message_ids or []),
        "source_refs": source_refs,
        "source_code": "chat",
        "source_kind": "chat",
        "index_status": "indexing_pending",
        "source_content_hash": source_hash,
        "provenance": {
            "actor_id": actor.id,
            "source_message_ids": list(message_ids or []),
            "source_content_hash": source_hash,
        },
        "metadata": {
            "importance": importance,
            "secret_handles": list(secret_handles),
        },
        "created_by": actor,
    }
    item, created = MemoryKnowledgeItem.objects.update_or_create(memory_id=memory_id, defaults=defaults)
    if not created and item.status != MemoryKnowledgeItem.Status.ACTIVE:
        item.status = MemoryKnowledgeItem.Status.ACTIVE
        item.save(update_fields=["status", "updated_at"])
    return item


def rebuild_memory_projection(*, scope: str, owner_user=None):
    """Regenerate the OKF ``index.md`` for a scope from the knowledge files on disk.

    ADR-0030 decision 4: the git commit is now the write journal; there is no
    ``MemoryKnowledgeEvent`` log and no DB-queryset-built ``_summary.md``. The
    index is rebuilt by walking the knowledge files themselves.
    """
    owner_user_id = owner_user.id if owner_user is not None else None
    if scope == MemoryKnowledgeItem.Scope.PERSONAL and owner_user_id is None:
        raise ValidationError("owner_user is required for personal memory projection.")
    return rebuild_knowledge_index(scope=scope, owner_user_id=owner_user_id)


def index_knowledge_item(item: MemoryKnowledgeItem, *, index_backends=("fulltext", "vector")):
    lifecycle = str((item.metadata or {}).get("lifecycle") or "current")
    if lifecycle != "current":
        # ADR-0030 decisions 4 & 8: a page proposed via the git
        # propose -> pending -> review -> stable primitive (an organization
        # candidacy proposal, or a classification downgrade held by
        # memory_reconcile) must not be discoverable by normal memory.search
        # until a knowledge owner accepts it. Guard here so this holds
        # regardless of which caller invokes indexing.
        if item.index_status != "indexing_pending":
            item.index_status = "indexing_pending"
            item.save(update_fields=["index_status", "updated_at"])
        return {"document_ids": [], "fact_ids": [], "knowledge_id": item.memory_id, "skipped": f"lifecycle:{lifecycle}"}
    source = _chat_memory_source(item.scope)
    selected_backends = set(index_backends or ())
    fulltext_backend = get_default_backend() if "fulltext" in selected_backends else None
    vector_backend = get_default_vector_backend() if "vector" in selected_backends else None
    document_id = _knowledge_document_id(item)
    body = read_knowledge_item_file(item).body
    stale_document_ids = list(
        MemorySearchDocument.objects.filter(
            knowledge_item=item,
            corpus_type=MemorySearchDocument.CorpusType.KNOWLEDGE,
        )
        .exclude(document_id=document_id)
        .values_list("document_id", flat=True)
    )
    if stale_document_ids and hasattr(fulltext_backend, "deactivate"):
        fulltext_backend.deactivate(stale_document_ids)
    if stale_document_ids and vector_backend is not None and hasattr(vector_backend, "deactivate"):
        vector_backend.deactivate(stale_document_ids)
    MemorySearchDocument.objects.filter(document_id__in=stale_document_ids).update(
        index_status=MemorySearchDocument.IndexStatus.DELETED,
        updated_at=timezone.now(),
    )
    metadata = {
        "corpus_type": "knowledge",
        "result_type": "knowledge",
        "memory_id": item.memory_id,
        "knowledge_id": item.memory_id,
        "scope": item.scope,
        "owner_user_id": item.owner_user_id,
        "source_code": item.source_code or source.code,
        "source_kind": item.source_kind or source.source_kind,
        "source_refs": item.source_refs,
        "source_message_ids": item.source_message_ids,
        "knowledge_file_path": item.knowledge_file_path,
    }
    existing_document = MemorySearchDocument.objects.filter(document_id=document_id).first()
    existing_versions = dict(((existing_document.metadata or {}).get("index_versions") if existing_document else {}) or {})
    if "fulltext" in selected_backends:
        existing_versions["fulltext"] = get_default_fulltext_schema_version()
    if "vector" in selected_backends:
        existing_versions["vector"] = LANCEDB_VECTOR_SCHEMA_VERSION
    metadata["index_versions"] = existing_versions
    document, _ = MemorySearchDocument.objects.update_or_create(
        document_id=document_id,
        defaults={
            "corpus_type": MemorySearchDocument.CorpusType.KNOWLEDGE,
            "object_kind": MemorySearchDocument.ObjectKind.KNOWLEDGE_ITEM,
            "knowledge_item": item,
            "body_hash": item.text_hash,
            "index_status": MemorySearchDocument.IndexStatus.READY,
            "metadata": metadata,
            "indexed_at": timezone.now(),
        },
    )
    record = MemoryIndexRecord(
        document_id=document.document_id,
        text=body,
        metadata={**metadata, "content_hash": item.text_hash},
        scope_tokens=item.scope_tokens,
        sensitivity=item.sensitivity,
        is_active=True,
    )
    if fulltext_backend is not None:
        fulltext_backend.upsert(record)
    if vector_backend is not None:
        vector_backend.upsert(record)
    item.index_status = "ready"
    item.save(update_fields=["index_status", "updated_at"])
    return {"document_ids": [document.document_id], "fact_ids": [], "knowledge_id": item.memory_id}


def edit_personal_memory(*, actor, memory_id: str, new_text: str):
    item = _get_owned_personal_memory(actor=actor, memory_id=memory_id)
    sanitized = sanitize_memory_text(new_text, actor=actor, scope=MemoryKnowledgeItem.Scope.PERSONAL)
    body = _normalize_memory_text(sanitized.text)
    item.text_hash = _sha256(body)
    item.kind = MemoryKnowledgeItem.Kind.SECRET_REFERENCE if sanitized.secret_handles else item.kind
    item.metadata = {**(item.metadata or {}), "secret_handles": list(sanitized.secret_handles)}
    item.index_status = "indexing_pending"
    item.save(update_fields=["text_hash", "kind", "metadata", "index_status", "updated_at"])
    file_result = write_knowledge_item_file(item, body=body, commit_message=f"Edit knowledge {item.memory_id}")
    rebuild_memory_projection(scope=item.scope, owner_user=item.owner_user)
    try:
        index_knowledge_item(item)
    except Exception as exc:
        enqueue_memory_queue_task(
            job_kind=MemoryQueueJobKind.REINDEX,
            source_code=item.source_code,
            idempotency_key=f"reindex:{item.memory_id}",
            payload={"memory_id": item.memory_id, "reason": str(exc)},
        )
    return {
        "memory_id": item.memory_id,
        "knowledge_file_commit": file_result.commit_hash,
        "status": item.status,
    }


def delete_personal_memory(*, actor, memory_id: str):
    item = _get_owned_personal_memory(actor=actor, memory_id=memory_id)
    body = read_knowledge_item_file(item).body
    item.status = MemoryKnowledgeItem.Status.DELETED
    item.index_status = "deleted"
    item.save(update_fields=["status", "index_status", "updated_at"])
    file_result = write_knowledge_item_file(item, body=body, commit_message=f"Delete knowledge {item.memory_id}")
    rebuild_memory_projection(scope=item.scope, owner_user=item.owner_user)
    document_ids = list(MemorySearchDocument.objects.filter(knowledge_item=item).values_list("document_id", flat=True))
    if document_ids:
        fulltext_backend = get_default_backend()
        if hasattr(fulltext_backend, "deactivate"):
            fulltext_backend.deactivate(document_ids)
        vector_backend = get_default_vector_backend()
        if vector_backend is not None and hasattr(vector_backend, "deactivate"):
            vector_backend.deactivate(document_ids)
        MemorySearchDocument.objects.filter(document_id__in=document_ids).update(
            index_status=MemorySearchDocument.IndexStatus.DELETED,
            updated_at=timezone.now(),
        )
    return {
        "memory_id": item.memory_id,
        "knowledge_file_commit": file_result.commit_hash,
        "status": item.status,
    }


def find_organization_candidate(source_item: MemoryKnowledgeItem) -> MemoryKnowledgeItem | None:
    """Return the existing organization candidate page proposed from ``source_item``, if any."""
    return (
        MemoryKnowledgeItem.objects.filter(
            scope=MemoryKnowledgeItem.Scope.ORGANIZATION,
            metadata__candidate_source_memory_id=source_item.memory_id,
        )
        .order_by("-created_at", "-id")
        .first()
    )


def create_organization_candidate(*, source_item: MemoryKnowledgeItem, created_by) -> MemoryKnowledgeItem:
    """Propose ``source_item`` (personal knowledge) for promotion to organization scope.

    ADR-0030 decisions 4 & 8: personal->organization candidacy rides the git
    ``propose -> pending -> review -> stable`` primitive instead of a
    ``MemoryKnowledgeCandidate`` row. The candidate is an organization-scope
    ``MemoryKnowledgeItem`` whose knowledge file carries ``lifecycle: pending``
    in its frontmatter (written to the repo as a real file + git commit), but
    ``index_knowledge_item`` skips pending items so ``memory.search`` cannot
    find it until a knowledge owner accepts it via the review UI.
    """
    existing = find_organization_candidate(source_item)
    if existing is not None:
        return existing
    body = _normalize_memory_text(read_knowledge_item_file(source_item).body)
    text_hash = _sha256(body)
    memory_id = f"chat:{MemoryKnowledgeItem.Scope.ORGANIZATION}:candidate:{source_item.pk}:{text_hash[:24]}"
    candidate = MemoryKnowledgeItem.objects.create(
        memory_id=memory_id,
        scope=MemoryKnowledgeItem.Scope.ORGANIZATION,
        owner_user=None,
        kind=source_item.kind,
        text_hash=text_hash,
        sensitivity=source_item.sensitivity,
        # The candidate is proposed *into* organization scope: it must carry
        # organization-visible scope tokens (not the personal owner's token
        # copied verbatim), so once accepted it is actually findable by the
        # organization, not just the original personal owner.
        scope_tokens=_scope_tokens_for_memory(scope=MemoryKnowledgeItem.Scope.ORGANIZATION),
        status=MemoryKnowledgeItem.Status.ACTIVE,
        source_refs=list(source_item.source_refs or []),
        source_code=source_item.source_code,
        source_kind=source_item.source_kind,
        index_status="indexing_pending",
        provenance={
            "candidate_source_memory_id": source_item.memory_id,
            "candidate_source_owner_user_id": source_item.owner_user_id,
        },
        metadata={
            "lifecycle": "pending",
            "candidate_source_memory_id": source_item.memory_id,
            "candidate_source_owner_user_id": source_item.owner_user_id,
        },
        created_by=created_by,
    )
    write_knowledge_item_file(
        candidate,
        body=body,
        commit_message=f"Propose organization candidate from {source_item.memory_id}",
    )
    rebuild_memory_projection(scope=MemoryKnowledgeItem.Scope.ORGANIZATION)
    return candidate


def propose_reflection_candidates(*, limit=100):
    # DEBT(ADR-0030-5b): reflection dataset-initiator goes here. In stage 5b,
    # when reflection notices a recurring series of like observations it also
    # proposes a `type: Dataset` page (pending review); on acceptance the
    # observation pages migrate into the data store and are marked superseded.
    # For now reflection only proposes personal->organization knowledge candidates.
    candidates = []
    queryset = (
        MemoryKnowledgeItem.objects.filter(scope=MemoryKnowledgeItem.Scope.PERSONAL, status=MemoryKnowledgeItem.Status.ACTIVE)
        .order_by("created_at", "id")
    )
    for item in queryset[:limit]:
        if find_organization_candidate(item) is not None:
            continue
        importance = str((item.metadata or {}).get("importance", "")).lower()
        if importance not in {"high", "org", "organization", "organization_candidate"}:
            continue
        candidates.append(create_organization_candidate(source_item=item, created_by=item.created_by))
    return candidates


def _load_messages(*, session, message_ids: list[int]):
    ids = [int(value) for value in message_ids or [] if str(value).isdigit()]
    if not ids:
        return []
    messages = list(
        ChatMessage.objects.filter(session=session, id__in=ids).order_by("created_at", "id")
    )
    if len(messages) != len(set(ids)):
        raise ValidationError("One or more message_ids do not belong to this chat session.")
    return messages


def _build_raw_memory_text(*, messages: Iterable[ChatMessage], user_note: str) -> str:
    parts = [message.content for message in messages if message.content]
    if user_note:
        parts.append(user_note)
    return "\n\n".join(parts)


def _source_refs_for_remember(*, session, message_ids: list[int]) -> list[dict[str, str]]:
    refs = []
    session_id = getattr(session, "id", None)
    if session_id:
        for message_id in message_ids or []:
            refs.append(
                {
                    "kind": "chat_message",
                    "value": f"chat_session:{session_id}/message:{message_id}",
                }
            )
    return refs


def _chat_memory_source(scope: str) -> MemorySource:
    code = CHAT_MEMORY_ORG_SOURCE if scope == MemoryKnowledgeItem.Scope.ORGANIZATION else CHAT_MEMORY_PERSONAL_SOURCE
    title = "Память организации из ИИ-чата" if scope == MemoryKnowledgeItem.Scope.ORGANIZATION else "Личная память из ИИ-чата"
    source, _ = MemorySource.objects.update_or_create(
        code=code,
        defaults={
            "title": title,
            "source_kind": "ai_chat",
            "domain": "chat_memory",
            "owner": "memory",
            "status": MemorySource.Status.ENABLED,
            "trust_status": MemorySource.TrustStatus.TRUSTED,
            "authority_class": (
                MemorySource.AuthorityClass.REVIEWED_ORG_KNOWLEDGE
                if scope == MemoryKnowledgeItem.Scope.ORGANIZATION
                else MemorySource.AuthorityClass.APPROVED_USER_MEMORY
            ),
            "trusted_for_context": True,
            "requires_source_review": False,
            "review_owner": "knowledge_owner" if scope == MemoryKnowledgeItem.Scope.ORGANIZATION else "memory_owner",
            "trusted_context_kinds": ["retrieved_chunk", "citation"],
            "untrusted_handling": "review_required",
            "sync_mode": "event_driven",
            "scope_rule": "chat_memory_scope",
            "sensitivity": "internal",
            "pii_policy": "secret_handle_redaction",
            "extractor_profile": CHAT_MEMORY_EXTRACTOR_VERSION,
            "chunking_profile": "short_business_event_v1",
            "index_profiles": ["fulltext_default"],
            "config": {"runtime_source": True, "scope": scope},
        },
    )
    return source


def _scope_tokens_for_memory(*, scope: str, owner_user=None) -> list[str]:
    if scope == MemoryKnowledgeItem.Scope.PERSONAL:
        return [f"user:{owner_user.id}"]
    return ["org:default"]


def _memory_id(*, scope: str, owner_user, text_hash: str) -> str:
    owner = f"user-{owner_user.id}" if owner_user else "org-default"
    return f"chat:{scope}:{owner}:{text_hash[:24]}"


def _knowledge_document_id(item: MemoryKnowledgeItem) -> str:
    return "knowledge:" + _sha256(f"{item.memory_id}:{item.text_hash}")[:40]


def _source_content_hash(*, messages, user_note: str) -> str:
    digest = hashlib.sha256()
    for message in messages:
        digest.update(str(message.id).encode("utf-8"))
        digest.update((message.content or "").encode("utf-8"))
    digest.update((user_note or "").encode("utf-8"))
    return digest.hexdigest()


def _sha256(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _normalize_memory_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _normalize_target_scope(value) -> str:
    item = str(value or TARGET_SCOPE_PERSONAL).strip().lower()
    if item not in {TARGET_SCOPE_PERSONAL, TARGET_SCOPE_ORGANIZATION}:
        raise ValidationError("target_scope must be 'personal' or 'organization'.")
    return item


def _normalize_message_ids(value) -> list[int]:
    if value is None or value == "":
        return []
    values = value if isinstance(value, list) else [value]
    message_ids = []
    for item in values:
        try:
            message_ids.append(int(item))
        except (TypeError, ValueError):
            raise ValidationError("message_ids must contain integers.")
    return message_ids


def _get_owned_personal_memory(*, actor, memory_id: str) -> MemoryKnowledgeItem:
    _assert_authenticated(actor)
    try:
        return MemoryKnowledgeItem.objects.get(
            memory_id=memory_id,
            scope=MemoryKnowledgeItem.Scope.PERSONAL,
            owner_user=actor,
            status=MemoryKnowledgeItem.Status.ACTIVE,
        )
    except MemoryKnowledgeItem.DoesNotExist as exc:
        raise PermissionDenied("Personal memory item is not available for this user.") from exc


def _assert_authenticated(actor):
    if not getattr(actor, "is_authenticated", False):
        raise PermissionDenied("Authentication required.")
