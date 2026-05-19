import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.json_utils import atomic_write_json

from .models import MemoryChunk, MemoryGraphFact, MemorySnapshot
from .security import assert_no_secrets


DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 120


@dataclass(frozen=True)
class ChunkPayload:
    chunk_id: str
    position: int
    text: str
    text_hash: str
    text_path: str
    metadata: dict


@dataclass(frozen=True)
class GraphFactPayload:
    fact_id: str
    source_chunk: MemoryChunk
    subject_id: str
    predicate: str
    object_id: str
    subject_type: str = ""
    object_type: str = ""
    confidence: str = "0.7500"
    extracted_by: str = "local-pattern-extractor-v1"
    metadata: dict | None = None


def index_snapshot_text(
    *,
    snapshot: MemorySnapshot,
    safe_text: str,
    vector_backend=None,
    graph_backend=None,
    chunk_size=DEFAULT_CHUNK_SIZE,
    chunk_overlap=DEFAULT_CHUNK_OVERLAP,
):
    if snapshot.status != MemorySnapshot.Status.READY:
        raise ValueError("Only ready snapshots can be indexed.")
    if not snapshot.pii_policy_applied:
        raise ValueError("Snapshot must pass the privacy pipeline before indexing.")

    safe_text = safe_text or ""
    assert_no_secrets(safe_text)

    chunk_payloads = build_chunk_payloads(
        snapshot=snapshot,
        safe_text=safe_text,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    with transaction.atomic():
        snapshot.safe_path = write_safe_snapshot(snapshot=snapshot, safe_text=safe_text)
        snapshot.save(update_fields=["safe_path", "updated_at"])
        chunks = upsert_chunks(snapshot=snapshot, chunk_payloads=chunk_payloads)
        stale_chunk_ids = deactivate_stale_snapshot_indexes(snapshot=snapshot, active_chunk_ids=[chunk.chunk_id for chunk in chunks])

    if vector_backend is not None:
        if stale_chunk_ids and hasattr(vector_backend, "deactivate"):
            vector_backend.deactivate(stale_chunk_ids)
        for chunk, payload in zip(chunks, chunk_payloads, strict=True):
            _backend_upsert_chunk(vector_backend, chunk=chunk, text=payload.text)

    graph_facts = []
    if graph_backend is not None:
        graph_facts = upsert_extracted_graph_facts(snapshot=snapshot, chunks=chunks, graph_backend=graph_backend)
        deactivate_stale_graph_facts(snapshot=snapshot, active_fact_ids=[fact.fact_id for fact in graph_facts])

    write_manifest(snapshot=snapshot, chunk_ids=[chunk.chunk_id for chunk in chunks], fact_ids=[fact.fact_id for fact in graph_facts])
    return {
        "snapshot_id": snapshot.id,
        "chunk_ids": [chunk.chunk_id for chunk in chunks],
        "fact_ids": [fact.fact_id for fact in graph_facts],
        "safe_path": snapshot.safe_path,
    }


def build_chunk_payloads(
    *,
    snapshot: MemorySnapshot,
    safe_text: str,
    chunk_size=DEFAULT_CHUNK_SIZE,
    chunk_overlap=DEFAULT_CHUNK_OVERLAP,
):
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive.")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be non-negative and smaller than chunk_size.")

    normalized = _normalize_text(safe_text)
    if not normalized:
        normalized = " "

    payloads = []
    for position, text in enumerate(_split_text(normalized, chunk_size=chunk_size, chunk_overlap=chunk_overlap)):
        text_hash = sha256_text(text)
        chunk_id = stable_chunk_id(snapshot=snapshot, position=position, text_hash=text_hash)
        text_path = str(_safe_chunk_path(snapshot, chunk_id))
        payloads.append(
            ChunkPayload(
                chunk_id=chunk_id,
                position=position,
                text=text,
                text_hash=text_hash,
                text_path=text_path,
                metadata={
                    "source_code": snapshot.source.code,
                    "source_object_id": snapshot.source_object_id,
                    "content_hash": snapshot.content_hash,
                },
            )
        )
    return payloads


def upsert_chunks(*, snapshot: MemorySnapshot, chunk_payloads):
    chunks = []
    for payload in chunk_payloads:
        _write_text_file(Path(payload.text_path), payload.text)
        chunk, _ = MemoryChunk.objects.update_or_create(
            chunk_id=payload.chunk_id,
            defaults={
                "snapshot": snapshot,
                "source_code": snapshot.source.code,
                "source_object_id": snapshot.source_object_id,
                "snapshot_hash": snapshot.content_hash,
                "position": payload.position,
                "text_path": payload.text_path,
                "text_hash": payload.text_hash,
                "metadata": payload.metadata,
                "scope_tokens": snapshot.scope_tokens,
                "sensitivity": snapshot.sensitivity,
                "valid_from": snapshot.valid_from,
                "valid_to": snapshot.valid_to,
                "is_active": True,
            },
        )
        chunks.append(chunk)
    return chunks


def deactivate_stale_snapshot_indexes(*, snapshot: MemorySnapshot, active_chunk_ids):
    active_chunk_ids = set(active_chunk_ids)
    stale_chunks = MemoryChunk.objects.filter(snapshot=snapshot, is_active=True).exclude(chunk_id__in=active_chunk_ids)
    stale_chunk_ids = list(stale_chunks.values_list("chunk_id", flat=True))
    stale_chunk_pks = list(stale_chunks.values_list("id", flat=True))
    stale_chunks.update(is_active=False, updated_at=timezone.now())
    MemoryGraphFact.objects.filter(snapshot=snapshot, is_active=True, source_chunk_id__in=stale_chunk_pks).update(
        is_active=False,
        updated_at=timezone.now(),
    )
    return stale_chunk_ids


def deactivate_snapshot_indexes(*, snapshot: MemorySnapshot):
    now = timezone.now()
    MemoryChunk.objects.filter(snapshot=snapshot, is_active=True).update(is_active=False, updated_at=now)
    MemoryGraphFact.objects.filter(snapshot=snapshot, is_active=True).update(is_active=False, updated_at=now)


def deactivate_stale_graph_facts(*, snapshot: MemorySnapshot, active_fact_ids):
    active_fact_ids = set(active_fact_ids)
    queryset = MemoryGraphFact.objects.filter(snapshot=snapshot, is_active=True)
    if active_fact_ids:
        queryset = queryset.exclude(fact_id__in=active_fact_ids)
    return queryset.update(is_active=False, updated_at=timezone.now())


def upsert_extracted_graph_facts(*, snapshot: MemorySnapshot, chunks, graph_backend):
    facts = []
    for chunk in chunks:
        for payload in extract_local_graph_facts(chunk):
            facts.append(_backend_upsert_fact(graph_backend, snapshot=snapshot, payload=payload))
    return facts


def extract_local_graph_facts(chunk: MemoryChunk):
    text = _read_text_file(Path(chunk.text_path))
    facts = []
    for match in re.finditer(r"\b(?P<subject>[A-Za-zА-Яа-яЁё0-9:_-]{3,})\s*->\s*(?P<object>[A-Za-zА-Яа-яЁё0-9:_-]{3,})\b", text):
        subject_id = match.group("subject")
        object_id = match.group("object")
        fact_id = stable_fact_id(chunk=chunk, subject_id=subject_id, predicate="mentions_relation", object_id=object_id)
        facts.append(
            GraphFactPayload(
                fact_id=fact_id,
                source_chunk=chunk,
                subject_id=subject_id,
                predicate="mentions_relation",
                object_id=object_id,
                metadata={"extractor": "arrow-pattern", "chunk_id": chunk.chunk_id},
            )
        )
    return facts


def write_safe_snapshot(*, snapshot: MemorySnapshot, safe_text: str):
    path = _safe_snapshot_path(snapshot)
    _write_text_file(path, safe_text)
    return str(path)


def write_manifest(*, snapshot: MemorySnapshot, chunk_ids, fact_ids):
    path = _manifest_path(snapshot)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        path,
        {
            "snapshot_id": snapshot.id,
            "source_code": snapshot.source.code,
            "source_object_id": snapshot.source_object_id,
            "content_hash": snapshot.content_hash,
            "chunk_ids": list(chunk_ids),
            "fact_ids": list(fact_ids),
            "updated_at": timezone.now().isoformat(),
        },
    )
    return str(path)


def stable_chunk_id(*, snapshot: MemorySnapshot, position: int, text_hash: str):
    return "chunk:" + sha256_text(f"{snapshot.source.code}:{snapshot.source_object_id}:{snapshot.content_hash}:{position}")[:32]


def stable_fact_id(*, chunk: MemoryChunk, subject_id: str, predicate: str, object_id: str):
    return "fact:" + sha256_text(f"{chunk.chunk_id}:{subject_id}:{predicate}:{object_id}")[:32]


def sha256_text(value: str):
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _backend_upsert_chunk(vector_backend, *, chunk: MemoryChunk, text: str):
    from .vector_backends import MemoryIndexRecord

    record = MemoryIndexRecord(
        chunk_id=chunk.chunk_id,
        text=text,
        metadata={
            **dict(chunk.metadata or {}),
            "source_code": chunk.source_code,
            "source_object_id": chunk.source_object_id,
            "snapshot_hash": chunk.snapshot_hash,
            "text_hash": chunk.text_hash,
        },
        scope_tokens=chunk.scope_tokens,
        sensitivity=chunk.sensitivity,
        is_active=chunk.is_active,
    )
    if hasattr(vector_backend, "upsert_chunk"):
        return vector_backend.upsert_chunk(chunk=chunk, text=text)
    if hasattr(vector_backend, "upsert"):
        return vector_backend.upsert(record)
    raise TypeError("vector_backend must provide upsert_chunk() or upsert().")


def _backend_upsert_fact(graph_backend, *, snapshot: MemorySnapshot, payload: GraphFactPayload):
    from .graph_backends import GraphFactRecord

    record = GraphFactRecord(
        fact_id=payload.fact_id,
        source_chunk=payload.source_chunk,
        snapshot=snapshot,
        subject_id=payload.subject_id,
        predicate=payload.predicate,
        object_id=payload.object_id,
        subject_type=payload.subject_type,
        object_type=payload.object_type,
        confidence=payload.confidence,
        extracted_by=payload.extracted_by,
        metadata=payload.metadata or {},
    )
    if hasattr(graph_backend, "upsert_facts"):
        result = graph_backend.upsert_facts([record])
        return result.records[0]
    if hasattr(graph_backend, "upsert_fact"):
        return graph_backend.upsert_fact(record)
    if hasattr(graph_backend, "upsert"):
        return graph_backend.upsert(record)
    raise TypeError("graph_backend must provide upsert_facts(), upsert_fact(), or upsert().")


def _normalize_text(text: str):
    return re.sub(r"\s+", " ", (text or "").strip())


def _split_text(text: str, *, chunk_size: int, chunk_overlap: int):
    step = chunk_size - chunk_overlap
    for start in range(0, len(text), step):
        yield text[start : start + chunk_size]
        if start + chunk_size >= len(text):
            break


def _write_text_file(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def _read_text_file(path: Path):
    return path.read_text(encoding="utf-8")


def _memory_data_dir(*parts):
    path = settings.DATA_DIR / "memory"
    for part in parts:
        path = path / _safe_path_component(str(part))
    return path


def _safe_snapshot_path(snapshot: MemorySnapshot):
    return _memory_data_dir(
        "safe_corpus",
        snapshot.source.code,
        snapshot.source_object_id,
        f"{snapshot.content_hash}.txt",
    )


def _safe_chunk_path(snapshot: MemorySnapshot, chunk_id: str):
    return _memory_data_dir(
        "safe_corpus",
        snapshot.source.code,
        snapshot.source_object_id,
        snapshot.content_hash,
        f"{chunk_id}.txt",
    )


def _manifest_path(snapshot: MemorySnapshot):
    return _memory_data_dir(
        "manifests",
        snapshot.source.code,
        snapshot.source_object_id,
        f"{snapshot.content_hash}.json",
    )


def _safe_path_component(value: str):
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return safe.strip("._") or "item"
