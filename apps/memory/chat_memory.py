from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.ai.models import ChatMessage

from .models import (
    MemoryIndexJob,
    MemoryKnowledgeCandidate,
    MemoryKnowledgeEvent,
    MemoryKnowledgeItem,
    MemorySearchDocument,
    MemorySource,
    MemoryWriteRequest,
)
from .knowledge_files import read_knowledge_item_file, rebuild_knowledge_summaries, write_knowledge_item_file
from .policies import can_write_organization_memory, can_write_personal_memory
from .secret_backends import get_secret_backend
from .security import scan_for_secrets
from .vector_backends import MemoryIndexRecord
from .vector_backends import LANCEDB_VECTOR_SCHEMA_VERSION, SQLITE_FTS_SCHEMA_VERSION
from .vector_backends import get_default_backend
from .vector_backends import get_default_vector_backend


CHAT_MEMORY_PERSONAL_SOURCE = "ai_chat_personal"
CHAT_MEMORY_ORG_SOURCE = "ai_chat_organization"
CHAT_MEMORY_SCHEMA_VERSION = "chat-memory-v1"
CHAT_MEMORY_EXTRACTOR_VERSION = "chat-memory-mvp-v1"


@dataclass(frozen=True)
class SanitizedMemoryText:
    text: str
    secret_handles: tuple[dict, ...]


def queue_memory_remember(*, actor, session, payload, request_id=""):
    _assert_authenticated(actor)
    target_scope = _normalize_target_scope(payload.get("target_scope"))
    if target_scope == MemoryWriteRequest.TargetScope.PERSONAL:
        if not can_write_personal_memory(actor, actor):
            raise PermissionDenied("Personal memory write is not allowed.")
    elif target_scope == MemoryWriteRequest.TargetScope.ORGANIZATION:
        if not can_write_organization_memory(actor):
            raise PermissionDenied("Organization memory write is not allowed for this user.")

    message_ids = _normalize_message_ids(payload.get("message_ids"))
    if not message_ids:
        latest = session.messages.filter(role=ChatMessage.Role.USER).order_by("-created_at", "-id").first()
        if latest:
            message_ids = [latest.id]
    if not message_ids and not str(payload.get("user_note", "")).strip():
        raise ValidationError("message_ids or user_note is required.")

    request = MemoryWriteRequest.objects.create(
        actor=actor,
        session=session,
        message_ids=message_ids,
        target_scope=target_scope,
        user_note=str(payload.get("user_note", "") or ""),
        importance=str(payload.get("importance", "") or ""),
        status=MemoryWriteRequest.Status.QUEUED,
    )
    job = MemoryIndexJob.objects.create(
        job_kind=MemoryIndexJob.JobKind.REMEMBER,
        status=MemoryIndexJob.Status.PENDING,
        request_id=request_id or str(request.request_id),
        payload={"memory_write_request_id": request.pk, "target_scope": target_scope},
        created_by=actor,
    )
    request.result = {"job_id": job.pk, "request_id": str(request.request_id)}
    request.save(update_fields=["result", "updated_at"])
    return {
        "request_id": str(request.request_id),
        "status": request.status,
        "target_scope": request.target_scope,
        "queued_at": request.created_at.isoformat(),
        "job_id": job.pk,
        "message": "Memory ingestion request queued.",
    }


def remember_memory_now(*, actor, session, payload, request_id=""):
    queued = queue_memory_remember(actor=actor, session=session, payload=payload, request_id=request_id)
    request = MemoryWriteRequest.objects.get(request_id=queued["request_id"])
    job = MemoryIndexJob.objects.filter(pk=queued["job_id"]).first()
    if job is not None:
        job.status = MemoryIndexJob.Status.RUNNING
        job.started_at = timezone.now()
        job.attempts += 1
        job.save(update_fields=["status", "started_at", "attempts", "updated_at"])
    try:
        processed = process_memory_write_request(request)
    except Exception as exc:
        if job is not None:
            job.status = MemoryIndexJob.Status.FAILED
            job.finished_at = timezone.now()
            job.error_message = str(exc)
            job.save(update_fields=["status", "finished_at", "error_message", "updated_at"])
        raise
    request.refresh_from_db()
    result = {
        "memory_id": processed["memory_id"],
        "request_id": queued["request_id"],
        "status": request.status,
        "target_scope": request.target_scope,
        "processed_at": request.processed_at.isoformat() if request.processed_at else "",
        "job_id": queued["job_id"],
        "event_id": processed["event_id"],
        "secret_handles": processed.get("secret_handles", []),
        "message": "Memory knowledge item saved.",
    }
    if job is not None:
        job.status = MemoryIndexJob.Status.SUCCEEDED
        job.finished_at = timezone.now()
        job.result = result
        job.error_message = ""
        job.save(update_fields=["status", "finished_at", "result", "error_message", "updated_at"])
    return result


@transaction.atomic
def process_memory_write_request(request: MemoryWriteRequest):
    if request.status not in {MemoryWriteRequest.Status.QUEUED, MemoryWriteRequest.Status.FAILED}:
        return request.result

    request.status = MemoryWriteRequest.Status.PROCESSING
    request.save(update_fields=["status", "updated_at"])

    try:
        source_messages = _load_source_messages(request)
        raw_text = _build_raw_memory_text(request=request, messages=source_messages)
        if not raw_text.strip():
            raise ValidationError("Memory request has no text to ingest.")

        sanitized = sanitize_memory_text(
            raw_text,
            actor=request.actor,
            scope=request.target_scope,
            source_metadata={"memory_write_request_id": request.pk},
        )
        knowledge_item = create_knowledge_item_from_request(
            request=request,
            safe_text=sanitized.text,
            messages=source_messages,
            secret_handles=sanitized.secret_handles,
        )
        file_result = write_knowledge_item_file(
            knowledge_item,
            body=_normalize_memory_text(sanitized.text),
            commit_message=f"Remember knowledge {knowledge_item.memory_id}",
        )
        event = append_knowledge_event(
            knowledge_item=knowledge_item,
            actor=request.actor,
            event_type=MemoryKnowledgeEvent.EventType.REMEMBERED,
            payload={
                "memory_write_request_id": request.pk,
                "target_scope": request.target_scope,
                "source_message_ids": list(request.message_ids or []),
                "secret_handles": list(sanitized.secret_handles),
            },
        )
        rebuild_memory_projection(scope=knowledge_item.scope, owner_user=knowledge_item.owner_user)
        index_knowledge_item(knowledge_item)

        result = {
            "memory_id": knowledge_item.memory_id,
            "event_id": str(event.event_id),
            "secret_handles": list(sanitized.secret_handles),
            "knowledge_file_path": file_result.relative_path,
            "knowledge_file_commit": file_result.commit_hash,
        }
        request.status = (
            MemoryWriteRequest.Status.ACCEPTED
            if request.target_scope == MemoryWriteRequest.TargetScope.ORGANIZATION
            else MemoryWriteRequest.Status.ACCEPTED
        )
        request.result = {**request.result, **result}
        request.error_message = ""
        request.processed_at = timezone.now()
        request.save(update_fields=["status", "result", "error_message", "processed_at", "updated_at"])
        return result
    except Exception as exc:
        request.status = MemoryWriteRequest.Status.FAILED
        request.error_message = str(exc)
        request.processed_at = timezone.now()
        request.save(update_fields=["status", "error_message", "processed_at", "updated_at"])
        raise


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


def create_knowledge_item_from_request(*, request: MemoryWriteRequest, safe_text: str, messages, secret_handles=()):
    text = _normalize_memory_text(safe_text)
    if not text:
        raise ValidationError("Memory text is empty after sanitization.")
    text_hash = _sha256(text)
    source_hash = _source_content_hash(messages=messages, user_note=request.user_note)
    scope = (
        MemoryKnowledgeItem.Scope.ORGANIZATION
        if request.target_scope == MemoryWriteRequest.TargetScope.ORGANIZATION
        else MemoryKnowledgeItem.Scope.PERSONAL
    )
    owner_user = request.actor if scope == MemoryKnowledgeItem.Scope.PERSONAL else None
    memory_id = _memory_id(scope=scope, owner_user=owner_user, text_hash=text_hash)
    defaults = {
        "scope": scope,
        "owner_user": owner_user,
        "kind": MemoryKnowledgeItem.Kind.SECRET_REFERENCE if secret_handles else MemoryKnowledgeItem.Kind.FACT,
        "text_hash": text_hash,
        "sensitivity": "internal" if not secret_handles else "confidential",
        "scope_tokens": _scope_tokens_for_memory(scope=scope, owner_user=owner_user),
        "status": MemoryKnowledgeItem.Status.ACTIVE,
        "source_session": request.session,
        "source_message_ids": list(request.message_ids or []),
        "source_refs": _source_refs_for_request(request),
        "source_code": "chat",
        "source_kind": "chat",
        "index_status": "indexing_pending",
        "source_content_hash": source_hash,
        "provenance": {
            "memory_write_request_id": request.pk,
            "source_message_ids": list(request.message_ids or []),
            "source_content_hash": source_hash,
        },
        "metadata": {
            "importance": request.importance,
            "secret_handles": list(secret_handles),
        },
        "created_by": request.actor,
    }
    item, created = MemoryKnowledgeItem.objects.update_or_create(memory_id=memory_id, defaults=defaults)
    if not created and item.status != MemoryKnowledgeItem.Status.ACTIVE:
        item.status = MemoryKnowledgeItem.Status.ACTIVE
        item.save(update_fields=["status", "updated_at"])
    return item


def append_knowledge_event(*, knowledge_item, actor, event_type, payload=None):
    event = MemoryKnowledgeEvent.objects.create(
        knowledge_item=knowledge_item,
        actor=actor,
        event_type=event_type,
        payload=_safe_event_payload(payload or {}),
    )
    _append_event_file(event)
    return event


def rebuild_memory_projection(*, scope: str, owner_user=None):
    items = MemoryKnowledgeItem.objects.filter(scope=scope, status=MemoryKnowledgeItem.Status.ACTIVE)
    if scope == MemoryKnowledgeItem.Scope.PERSONAL:
        if owner_user is None:
            raise ValidationError("owner_user is required for personal memory projection.")
        items = items.filter(owner_user=owner_user)
    elif scope == MemoryKnowledgeItem.Scope.ORGANIZATION:
        items = items.filter(owner_user__isnull=True)

    records = []
    for item in items.order_by("created_at", "id"):
        try:
            body = read_knowledge_item_file(item).body
        except ValidationError:
            body = ""
        records.append(
            {
                "memory_id": item.memory_id,
                "kind": item.kind,
                "text": body,
                "sensitivity": item.sensitivity,
                "scope_tokens": item.scope_tokens,
                "updated_at": item.updated_at.isoformat(),
                "metadata": item.metadata,
            }
        )
    rebuild_knowledge_summaries(scope=scope, owner_user=owner_user)
    return records


def index_knowledge_item(item: MemoryKnowledgeItem, *, index_backends=("fulltext", "vector")):
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
        existing_versions["fulltext"] = SQLITE_FTS_SCHEMA_VERSION
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
    write_knowledge_item_file(item, body=body, commit_message=f"Edit knowledge {item.memory_id}")
    event = append_knowledge_event(
        knowledge_item=item,
        actor=actor,
        event_type=MemoryKnowledgeEvent.EventType.EDITED,
        payload={"secret_handles": list(sanitized.secret_handles)},
    )
    rebuild_memory_projection(scope=item.scope, owner_user=item.owner_user)
    index_knowledge_item(item)
    return {"memory_id": item.memory_id, "event_id": str(event.event_id), "status": item.status}


def delete_personal_memory(*, actor, memory_id: str):
    item = _get_owned_personal_memory(actor=actor, memory_id=memory_id)
    body = read_knowledge_item_file(item).body
    item.status = MemoryKnowledgeItem.Status.DELETED
    item.index_status = "deleted"
    item.save(update_fields=["status", "index_status", "updated_at"])
    write_knowledge_item_file(item, body=body, commit_message=f"Delete knowledge {item.memory_id}")
    event = append_knowledge_event(
        knowledge_item=item,
        actor=actor,
        event_type=MemoryKnowledgeEvent.EventType.DELETED,
        payload={},
    )
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
    return {"memory_id": item.memory_id, "event_id": str(event.event_id), "status": item.status}


def create_organization_candidate(*, source_item: MemoryKnowledgeItem, created_by):
    proposed_text = read_knowledge_item_file(source_item).body
    candidate, _ = MemoryKnowledgeCandidate.objects.get_or_create(
        source_item=source_item,
        status=MemoryKnowledgeCandidate.Status.PROPOSED,
        defaults={
            "proposed_text": proposed_text,
            "proposed_payload": {
                "source_memory_id": source_item.memory_id,
                "source_owner_user_id": source_item.owner_user_id,
                "metadata": source_item.metadata,
            },
            "evidence": [source_item.provenance],
            "created_by": created_by,
        },
    )
    return candidate


def process_queued_memory_requests(*, limit=100):
    processed = []
    queryset = MemoryWriteRequest.objects.filter(
        status=MemoryWriteRequest.Status.QUEUED
    ).order_by("created_at", "id")[:limit]
    for request in queryset:
        job = _memory_write_request_job(request)
        if job is not None:
            job.status = MemoryIndexJob.Status.RUNNING
            job.started_at = timezone.now()
            job.attempts += 1
            job.save(update_fields=["status", "started_at", "attempts", "updated_at"])
        try:
            result = process_memory_write_request(request)
        except Exception as exc:
            if job is not None:
                job.status = MemoryIndexJob.Status.FAILED
                job.finished_at = timezone.now()
                job.error_message = str(exc)
                job.save(update_fields=["status", "finished_at", "error_message", "updated_at"])
            raise
        if job is not None:
            job.status = MemoryIndexJob.Status.SUCCEEDED
            job.finished_at = timezone.now()
            job.result = result
            job.error_message = ""
            job.save(update_fields=["status", "finished_at", "result", "error_message", "updated_at"])
        processed.append(result)
    return processed


def propose_reflection_candidates(*, limit=100):
    candidates = []
    queryset = (
        MemoryKnowledgeItem.objects.filter(scope=MemoryKnowledgeItem.Scope.PERSONAL, status=MemoryKnowledgeItem.Status.ACTIVE)
        .order_by("created_at", "id")
    )
    for item in queryset[:limit]:
        if item.organization_candidates.exists():
            continue
        importance = str((item.metadata or {}).get("importance", "")).lower()
        if importance not in {"high", "org", "organization", "organization_candidate"}:
            continue
        candidates.append(create_organization_candidate(source_item=item, created_by=item.created_by))
    return candidates


def _load_source_messages(request: MemoryWriteRequest):
    ids = [int(value) for value in request.message_ids or [] if str(value).isdigit()]
    if not ids:
        return []
    messages = list(
        ChatMessage.objects.filter(session=request.session, id__in=ids).order_by("created_at", "id")
    )
    if len(messages) != len(set(ids)):
        raise ValidationError("One or more message_ids do not belong to this chat session.")
    return messages


def _memory_write_request_job(request: MemoryWriteRequest):
    return (
        MemoryIndexJob.objects.filter(
            job_kind=MemoryIndexJob.JobKind.REMEMBER,
            payload__memory_write_request_id=request.pk,
        )
        .order_by("-created_at", "-id")
        .first()
    )


def _build_raw_memory_text(*, request: MemoryWriteRequest, messages: Iterable[ChatMessage]) -> str:
    parts = [message.content for message in messages if message.content]
    if request.user_note:
        parts.append(request.user_note)
    return "\n\n".join(parts)


def _source_refs_for_request(request: MemoryWriteRequest) -> list[dict[str, str]]:
    refs = []
    if request.session_id:
        for message_id in request.message_ids or []:
            refs.append(
                {
                    "kind": "chat_message",
                    "value": f"chat_session:{request.session_id}/message:{message_id}",
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


def _legacy_event_log_dir(*, scope: str, owner_user=None) -> Path:
    if scope == MemoryKnowledgeItem.Scope.PERSONAL:
        if owner_user is None:
            raise ValidationError("owner_user is required for personal memory event log path.")
        return Path(settings.DATA_DIR) / "memory" / "chat_knowledge" / "users" / str(owner_user.id)
    return Path(settings.DATA_DIR) / "memory" / "chat_knowledge" / "org" / "default"


def _append_event_file(event: MemoryKnowledgeEvent):
    """Write a legacy append-only event log; knowledge text lives in data/knowledge_repo."""
    item = event.knowledge_item
    if item is None:
        return
    base_dir = _legacy_event_log_dir(scope=item.scope, owner_user=item.owner_user)
    now = event.created_at or timezone.now()
    event_path = base_dir / "events" / f"{now:%Y-%m}.jsonl"
    event_payload = {
        "event_id": str(event.event_id),
        "event_type": event.event_type,
        "memory_id": item.memory_id,
        "scope": item.scope,
        "owner_user_id": item.owner_user_id,
        "payload": event.payload,
        "created_at": now.isoformat(),
        "actor_id": event.actor_id,
    }
    event_path.parent.mkdir(parents=True, exist_ok=True)
    with event_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event_payload, ensure_ascii=False, sort_keys=True) + "\n")


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
    item = str(value or MemoryWriteRequest.TargetScope.PERSONAL).strip().lower()
    if item not in {MemoryWriteRequest.TargetScope.PERSONAL, MemoryWriteRequest.TargetScope.ORGANIZATION}:
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


def _safe_event_payload(payload: dict) -> dict:
    blocked_keys = {"value", "secret", "password", "token", "api_key", "private_key"}
    return {str(key): value for key, value in dict(payload or {}).items() if str(key).lower() not in blocked_keys}


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
