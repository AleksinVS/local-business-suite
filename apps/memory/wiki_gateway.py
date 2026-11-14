"""Actor-scoped OKF tools. All model-visible content comes from a registered Git revision."""
import inspect
import posixpath
import re
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError

from .crow_provider import (
    CrowDecisionConfig, CrowPage, CrowUnavailable, classify_crow_relation, classify_proposed_change,
    search_crow_pages,
)
from .deidentification import detect_pii
from .knowledge_files import knowledge_repo_root
from .models import MemoryKnowledgeItem
from .policies import resolve_active_actor, user_scope_tokens
from .routing import resolve_retrieval_route
from .security import scan_for_secrets
from .wiki_config import wiki_article_id, wiki_bundles
from .wiki_reconcile import (
    read_wiki_snapshot, reconcile_wiki_bundle, registered_wiki_notes, wiki_blob, wiki_head, wiki_snapshot_ready,
)
from .wiki_sources import wiki_source_preview, wiki_sources_allowed

_DENIED = "Статья или раздел вики недоступны."
_RETRY = "Редакция вики изменилась или ожидает сверки. Повторите поиск."


def _bundle_for(actor, name, *, write=False):
    if not isinstance(name, str):
        raise PermissionDenied(_DENIED)
    bundle = wiki_bundles().get(name)
    tokens = user_scope_tokens(resolve_active_actor(actor, force_refresh=True))
    if not bundle or not bundle.model_context or not tokens.intersection(bundle.read_tokens):
        raise PermissionDenied(_DENIED)
    # Tool output can be routed to a remote assistant. Local-only material
    # needs a verified runtime destination before it can use this gateway.
    route = resolve_retrieval_route(bundle.sensitivity).routes[bundle.sensitivity]
    if not route.get("cloud_allowed", False):
        raise PermissionDenied(_DENIED)
    if write and (bundle.note_read_tokens or not tokens.intersection(bundle.write_tokens)):
        raise PermissionDenied(_DENIED)
    return bundle, tokens


def _safe_text(text):
    return not scan_for_secrets(text).blocked and not any(
        finding.entity_type != "DATE" for finding in detect_pii(text)
    )


def _available(actor, bundle):
    snapshot = read_wiki_snapshot(bundle)
    return snapshot, _visible(actor, bundle, snapshot)


def _visible(actor, bundle, snapshot):
    current, tokens = _bundle_for(actor, bundle.bundle_id)
    if current != bundle or not wiki_snapshot_ready(bundle, snapshot.revision):
        raise ValidationError(_RETRY)
    registered = registered_wiki_notes(bundle, snapshot.revision)
    visible = {}
    for key, item in registered.items():
        note = snapshot.notes.get(key)
        if note is None or item.metadata.get("wiki_blob_oid") != note.blob_oid:
            continue
        if key in bundle.note_read_tokens and not tokens.intersection(bundle.note_read_tokens[key]):
            continue
        if note.metadata.get("sources") or not wiki_sources_allowed(actor, bundle, note.metadata.get("source_refs", [])):
            continue
        # Examine the complete file, including arbitrary imported YAML, before
        # returning it or including text in a classifier/search request.
        markdown = wiki_blob(knowledge_repo_root(), note.blob_oid).decode("utf-8-sig")
        if _safe_text(markdown) and _safe_text(note.path):
            visible[key] = (note, item, markdown)
    # A Markdown link can itself disclose a hidden neighbor's title/path. Remove
    # indirect dependencies to a fixed point before the ranker sees any Note.
    if len(visible) != len(snapshot.notes):
        visible = _without_hidden_links(visible, snapshot)
    return visible


def _without_hidden_links(visible, snapshot):
    by_path = {note.path: key for key, note in snapshot.notes.items()}
    incoming = {}
    unsafe = set()
    for key, (note, _, markdown) in visible.items():
        # Only the normal inline Markdown link format is supported across mixed
        # audiences. Native embeds, reference definitions and raw HTML need a resolver.
        if re.search(r"\[\[|^\s*\[[^\]]+\]:|<[/!a-zA-Z]", markdown, re.MULTILINE):
            unsafe.add(key)
            continue
        for dest in re.findall(r"\]\(\s*([^()\s]+)", markdown):
            try:
                target = urlsplit(unquote(dest))
            except ValueError:
                unsafe.add(key)
                continue
            if target.scheme or target.netloc or not target.path:
                continue
            other = by_path.get(posixpath.normpath(posixpath.join(posixpath.dirname(note.path), target.path)))
            if other is None or other not in visible:
                unsafe.add(key)
            else:
                incoming.setdefault(other, []).append(key)
    pending = list(unsafe)
    while pending:
        for predecessor in incoming.get(pending.pop(), []):
            if predecessor not in unsafe:
                unsafe.add(predecessor)
                pending.append(predecessor)
    return {key: value for key, value in visible.items() if key not in unsafe}


def _page(entry, revision):
    note = entry[0]
    return CrowPage(note.knowledge_id, revision, str(note.metadata.get("title") or ""),
                    str(note.metadata.get("description") or ""), note.body)


def _basic_search(query, pages, limit):
    words = set(re.findall(r"\w+", query.casefold()))
    scores = []
    for p in pages:
        text = f"{p.title} {p.description} {p.body}".casefold()
        score = sum(text.count(word) for word in words)
        if score:
            scores.append((-score, p.knowledge_id))
    return [key for _, key in sorted(scores)[:limit]]


def _details(entry, bundle, revision):
    note, item, _ = entry
    return {"knowledge_id": note.knowledge_id, "path": note.path[len(bundle.path) + 1:],
            "title": str(note.metadata.get("title") or ""), "revision": revision,
            "confirmation_state": item.metadata["confirmation_state"]}


def search_wiki(actor, *, bundle_id="", query="", limit=8):
    if not isinstance(query, str) or len(query) > 2000 or type(limit) is not int or not 1 <= limit <= 50:
        raise ValidationError("Проверьте запрос и limit (1–50).")
    if not bundle_id:
        names = []
        for name in wiki_bundles():
            try:
                _bundle_for(actor, name)
            except PermissionDenied:
                continue
            names.append(name)
        return {"bundles": sorted(names)}
    bundle, _ = _bundle_for(actor, bundle_id)
    snapshot, entries = _available(actor, bundle)
    pages = [_page(entry, snapshot.revision) for entry in entries.values()]
    engine = settings.LOCAL_BUSINESS_WIKI_SEARCH
    if not query.strip():
        keys = sorted(entries)[:limit]
    elif engine == "basic":
        keys = _basic_search(query, pages, limit)
    elif engine == "crow":
        try:
            keys = search_crow_pages(query, pages, limit=limit)
        except CrowUnavailable as exc:
            raise ValidationError(str(exc)) from exc
    else:
        raise ValidationError("Неизвестный поисковый адаптер вики.")
    current = _visible(actor, bundle, snapshot)
    items = [_details(current[key], bundle, snapshot.revision) for key in keys if key in current]
    return {"revision": snapshot.revision, "items": items, "engine": engine}


def get_wiki(actor, *, bundle_id, knowledge_id="", path=""):
    if bool(knowledge_id) == bool(path):
        raise ValidationError("Укажите ID статьи или путь от корня раздела.")
    bundle, _ = _bundle_for(actor, bundle_id)
    snapshot, entries = _available(actor, bundle)
    if path:
        entry = next((row for row in entries.values() if row[0].path == f"{bundle.path}/{path}"), None)
    else:
        entry = entries.get(knowledge_id)
    if not entry:
        raise PermissionDenied(_DENIED)
    if wiki_head(knowledge_repo_root()) != snapshot.revision:
        raise ValidationError(_RETRY)
    return {**_details(entry, bundle, snapshot.revision), "markdown": entry[2]}


def compare_wiki(actor, *, bundle_id, left_id, right_id="", proposed_text="", source_ref=None):
    bundle, _ = _bundle_for(actor, bundle_id)
    snapshot, entries = _available(actor, bundle)
    if bool(right_id) == bool(proposed_text) or (right_id and source_ref is not None):
        raise ValidationError("Укажите вторую статью или предлагаемую правку с её source_ref.")
    if left_id not in entries or (right_id and right_id not in entries):
        raise PermissionDenied(_DENIED)
    config = CrowDecisionConfig(provider=settings.LOCAL_BUSINESS_WIKI_DECISION_PROVIDER,
                                model=settings.LOCAL_BUSINESS_WIKI_DECISION_MODEL,
                                base_url=settings.LOCAL_BUSINESS_WIKI_DECISION_URL)
    left = _page(entries[left_id], snapshot.revision)
    try:
        if right_id:
            result = classify_crow_relation(left, _page(entries[right_id], snapshot.revision), config=config)
        else:
            if not isinstance(proposed_text, str) or len(proposed_text) > 16000 or not _safe_text(proposed_text):
                raise ValidationError("Предлагаемый текст не прошёл проверку.")
            if not wiki_sources_allowed(actor, bundle, [source_ref]):
                raise PermissionDenied(_DENIED)
            result = classify_proposed_change(left, proposed_text, config=config)
    except (CrowUnavailable, ValueError) as exc:
        raise ValidationError(str(exc)) from exc
    current = _visible(actor, bundle, snapshot)
    if left_id not in current or (right_id and right_id not in current):
        raise PermissionDenied(_DENIED)
    if source_ref and not wiki_sources_allowed(actor, bundle, [source_ref]):
        raise PermissionDenied(_DENIED)
    return {**result, "revision": snapshot.revision, "left_id": left_id, "right_id": right_id}


def edit_wiki(actor, *, bundle_id, expected_revision, files):
    from .wiki_files import edit_wiki_files

    bundle, _ = _bundle_for(actor, bundle_id, write=True)
    if not isinstance(files, dict) or len(files) > 32 or any(
        not isinstance(path, str) or not _safe_text(path)
        or text is not None and (not isinstance(text, str) or len(text) > 128_000)
        for path, text in files.items()
    ):
        raise ValidationError("Ожидается до 32 Markdown-файлов по 128 000 символов.")

    def authorize():
        current, _ = _bundle_for(actor, bundle_id, write=True)
        if current != bundle:
            raise PermissionDenied(_DENIED)
        snapshot, visible = _available(actor, bundle)
        # Rebuilding indexes may read neighboring titles. Only write a bundle
        # when the entire inventory is safe for this author and its audience.
        if len(visible) != len(snapshot.notes):
            raise PermissionDenied(_DENIED)

    def validate_content(path, markdown, metadata):
        # Retired IDs and native aliases remain reserved across renames/deletions.
        key = wiki_article_id(bundle, metadata)
        existing = MemoryKnowledgeItem.objects.filter(memory_id=key).first()
        if existing and (existing.source_kind != "crow_note" or
                         existing.metadata.get("wiki_bundle_id") != bundle_id or existing.status != "active"):
            raise ValidationError("Идентификатор статьи занят.")
        native = metadata.get("id")
        if native:
            peers = MemoryKnowledgeItem.objects.filter(source_kind="crow_note", metadata__wiki_bundle_id=bundle_id)
            if any(native in info.get("wiki_native_ids", []) for info in peers.exclude(memory_id=key)
                   .values_list("metadata", flat=True)):
                raise ValidationError("Нативный идентификатор занят.")
        refs = metadata.get("source_refs")
        if metadata.get("status", "stable") != "stable":
            raise ValidationError("Для авторской статьи используйте status: stable или опустите поле.")
        if not _safe_text(markdown) or not refs or metadata.get("sources") or not wiki_sources_allowed(actor, bundle, refs):
            raise ValidationError("Проверьте основания статьи, аудиторию и наличие персональных данных.")

    # A process can lose its response between the Git fast-forward and the
    # database checkpoint. Rebuild from Git so the writer can recognize a retry.
    head = wiki_head(knowledge_repo_root())
    if not wiki_snapshot_ready(bundle, head):
        reconcile_wiki_bundle(bundle)
    result = edit_wiki_files(bundle=bundle, expected_revision=expected_revision, files=files,
                             authorize=authorize, validate_content=validate_content)
    try:
        state = reconcile_wiki_bundle(bundle)
        ready = state["status"] == "ready" and state["revision"] == result["revision"]
    except DatabaseError:
        ready = False
    return {**result, "index_status": "ready" if ready else "index_pending"}


def get_source(actor, *, bundle_id, source_code, source_object_id):
    bundle, _ = _bundle_for(actor, bundle_id)
    return wiki_source_preview(actor, bundle, source_code, source_object_id)


def wiki_tool(action, actor, payload):
    handlers = {"search": search_wiki, "get": get_wiki, "edit": edit_wiki,
                "compare": compare_wiki, "source": get_source}
    handler = handlers[action]
    try:
        inspect.signature(handler).bind(actor, **payload)
    except TypeError:
        raise ValidationError("Некорректные параметры инструмента вики.") from None
    for key in ("bundle_id", "knowledge_id", "path", "left_id", "right_id"):
        if key in payload and not isinstance(payload[key], str):
            raise ValidationError("Ожидается строковый идентификатор.")
    return handler(actor, **payload)


def _wiki_memory_result(entry, revision, request_id):
    note, item, _ = entry
    return {
        "result_type": "knowledge", "knowledge_id": note.knowledge_id, "text": note.body,
        "source_refs": note.metadata.get("source_refs") or [], "source_kind": item.source_kind,
        "source_code": item.source_code, "scope": item.scope, "index_status": item.index_status,
        "knowledge_file_path": note.path, "request_id": request_id, "revision": revision,
    }


def read_wiki_memory(actor, *, item, request_id=""):
    """Use the registered, currently authorized projection even for an old model instance."""
    bundle, _ = _bundle_for(actor, (item.metadata or {}).get("wiki_bundle_id"))
    snapshot, visible = _available(actor, bundle)
    entry = visible.get(item.memory_id)
    if not entry or entry[1].pk != item.pk:
        raise PermissionDenied(_DENIED)
    return _wiki_memory_result(entry, snapshot.revision, request_id)


def search_wiki_memory(actor, *, bundle_id, corpus, query, sensitivity, limit, request_id=""):
    """Scoped memory.search. Its history/audit discriminator is meta.search_mode=wiki_bundle."""
    from .config_documents import get_memory_document_payload
    from .services import record_access_audit, sha256_text

    trace = {"search_mode": "wiki_bundle"}
    digest = sha256_text(query.strip() if isinstance(query, str) else "")
    try:
        if not isinstance(bundle_id, str) or not bundle_id.strip() or corpus != "knowledge":
            raise ValidationError("Выберите раздел Wiki и корпус knowledge.")
        if not isinstance(query, str) or not query.strip() or type(limit) is not int or not 1 <= limit <= 50:
            raise ValidationError("Проверьте запрос и максимальное количество статей.")
        bundle, _ = _bundle_for(actor, bundle_id)
        route = resolve_retrieval_route(sensitivity)
        if bundle.sensitivity not in route.allowed_sensitivities:
            raise PermissionDenied(_DENIED)
        ranked = search_wiki(actor, bundle_id=bundle_id, query=query, limit=limit)
        snapshot, visible = _available(actor, bundle)
        if snapshot.revision != ranked["revision"]:
            raise ValidationError(_RETRY)
        budget = (get_memory_document_payload("memory.contract.retrieval_budget") or {}).get("context_packing", {})
        max_items = min(limit, int(budget.get("max_items", 8)))
        # Use the same four-characters-per-token estimate as memory retrieval.
        characters_left = max(0, int(budget.get("max_tokens", 1200)) * 4)
        items, citations = [], []
        for hit in ranked["items"]:
            if len(items) >= max_items or not characters_left:
                break
            entry = visible.get(hit["knowledge_id"])
            if entry is None:
                continue
            note, item, _ = entry
            document_id = f"wiki:{bundle_id}:{note.knowledge_id}"
            citation_id = f"memory-document:{document_id}:{snapshot.revision}"
            citation = {"id": citation_id, "document_id": document_id, "kind": "knowledge",
                        "knowledge_id": note.knowledge_id, "result_type": "knowledge", "source_code": item.source_code,
                        "source_kind": item.source_kind, "snapshot_hash": snapshot.revision,
                        "text_hash": item.text_hash, "sensitivity": bundle.sensitivity}
            text = note.body[:characters_left]
            items.append({"id": document_id, "kind": "knowledge", "result_type": "knowledge",
                          "knowledge_id": note.knowledge_id, "text": text, "citation_ids": [citation_id],
                          "source_refs": note.metadata.get("source_refs") or [], "source_code": item.source_code,
                          "source_kind": item.source_kind, "index_status": item.index_status,
                          "metadata": {"sensitivity": bundle.sensitivity, "revision": snapshot.revision,
                                       "confirmation_state": item.metadata["confirmation_state"]}})
            citations.append(citation)
            characters_left -= len(text)
        trace.update(revision=snapshot.revision, returned_count=len(items), citation_count=len(citations))
        # Audit is durable. Do not store a Note's text, title, path, source refs or query in it.
        record_access_audit(actor=actor, request_id=request_id, query_hash=digest,
                            policy_decision="allowed", retrieval_trace=trace)
        return {"items": items, "citations": citations,
                "meta": {**trace, "route": route.as_trace(), "limit": limit, "query_hash": digest,
                         "request_id": request_id, "engine": ranked["engine"], "corpus_types": ["knowledge"]}}
    except (PermissionDenied, ValidationError):
        if getattr(actor, "pk", None):
            record_access_audit(actor=actor, request_id=request_id, query_hash=digest,
                                policy_decision="denied", retrieval_trace=trace)
        raise
