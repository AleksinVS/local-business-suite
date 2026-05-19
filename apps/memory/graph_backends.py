from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, NoReturn, Protocol, runtime_checkable

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from .models import MemoryChunk, MemoryGraphFact, MemorySnapshot
from .policies import can_access_graph_fact, scope_tokens_match


@dataclass(frozen=True)
class GraphFactRecord:
    fact_id: str
    subject_id: str
    predicate: str
    object_id: str
    source_chunk: MemoryChunk | None = None
    chunk_id: str = ""
    source_chunk_pk: int | None = None
    snapshot: MemorySnapshot | None = None
    snapshot_id: int | None = None
    snapshot_hash: str = ""
    subject_type: str = ""
    object_type: str = ""
    confidence: Decimal | float | int | str = Decimal("0")
    extracted_by: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    scope_tokens: Sequence[str] | None = None
    sensitivity: str = ""
    valid_from: Any = None
    valid_to: Any = None
    is_active: bool = True


@dataclass(frozen=True)
class GraphFactUpsertResult:
    created_count: int
    updated_count: int
    records: tuple[MemoryGraphFact, ...]

    @property
    def fact_ids(self) -> tuple[str, ...]:
        return tuple(record.fact_id for record in self.records)


@runtime_checkable
class GraphMemoryBackend(Protocol):
    def upsert_facts(self, facts: Iterable[GraphFactRecord | Mapping[str, Any]]) -> GraphFactUpsertResult:
        """Create or update graph facts by stable fact_id."""
        ...

    def deactivate_facts(
        self,
        *,
        snapshot: MemorySnapshot | None = None,
        snapshot_id: int | None = None,
        fact_ids: Iterable[str] | None = None,
        valid_to: Any = None,
    ) -> int:
        """Deactivate facts by snapshot and/or fact_id without deleting provenance."""
        ...

    def filter_facts(
        self,
        *,
        subject_id: str | Sequence[str] | None = None,
        predicate: str | Sequence[str] | None = None,
        object_id: str | Sequence[str] | None = None,
        scope_tokens: str | Iterable[str] | None = None,
        sensitivity: str | Sequence[str] | None = None,
        active_only: bool = True,
        user: Any = None,
        limit: int | None = None,
    ) -> list[MemoryGraphFact]:
        """Return Django records after backend candidate filtering and policy checks."""
        ...

    def search_facts(
        self,
        query: str,
        *,
        scope_tokens: str | Iterable[str] | None = None,
        sensitivity: str | Sequence[str] | None = None,
        active_only: bool = True,
        user: Any = None,
        limit: int | None = 100,
    ) -> list[MemoryGraphFact]:
        """Search graph facts and return Django records after policy checks."""
        ...


class DjangoGraphMemoryBackend:
    """Graph backend backed by MemoryGraphFact as the source of truth."""

    def upsert_facts(self, facts: Iterable[GraphFactRecord | Mapping[str, Any]]) -> GraphFactUpsertResult:
        created_count = 0
        updated_count = 0
        records: list[MemoryGraphFact] = []

        with transaction.atomic():
            for value in facts:
                fact = _coerce_fact_record(value)
                source_chunk = _resolve_source_chunk(fact)
                snapshot = source_chunk.snapshot
                _validate_provenance(fact=fact, source_chunk=source_chunk, snapshot=snapshot)

                defaults = _build_fact_defaults(fact=fact, source_chunk=source_chunk, snapshot=snapshot)
                record, created = MemoryGraphFact.objects.update_or_create(
                    fact_id=fact.fact_id,
                    defaults=defaults,
                )
                records.append(record)
                if created:
                    created_count += 1
                else:
                    updated_count += 1

        return GraphFactUpsertResult(
            created_count=created_count,
            updated_count=updated_count,
            records=tuple(records),
        )

    def deactivate_facts(
        self,
        *,
        snapshot: MemorySnapshot | None = None,
        snapshot_id: int | None = None,
        fact_ids: Iterable[str] | None = None,
        valid_to: Any = None,
    ) -> int:
        queryset = MemoryGraphFact.objects.filter(is_active=True)
        fact_id_list = list(fact_ids) if fact_ids is not None else None

        if snapshot is None and snapshot_id is None and fact_id_list is None:
            raise ValueError("Provide snapshot, snapshot_id, or fact_ids to deactivate graph facts.")

        if snapshot is not None:
            queryset = queryset.filter(snapshot=snapshot)
        elif snapshot_id is not None:
            queryset = queryset.filter(snapshot_id=snapshot_id)

        if fact_id_list is not None:
            if not fact_id_list:
                return 0
            queryset = queryset.filter(fact_id__in=fact_id_list)

        return queryset.update(is_active=False, valid_to=valid_to or timezone.now())

    def deactivate_snapshot_facts(self, snapshot: MemorySnapshot, *, valid_to: Any = None) -> int:
        return self.deactivate_facts(snapshot=snapshot, valid_to=valid_to)

    def deactivate_fact_ids(self, fact_ids: Iterable[str], *, valid_to: Any = None) -> int:
        return self.deactivate_facts(fact_ids=fact_ids, valid_to=valid_to)

    def filter_facts(
        self,
        *,
        subject_id: str | Sequence[str] | None = None,
        predicate: str | Sequence[str] | None = None,
        object_id: str | Sequence[str] | None = None,
        scope_tokens: str | Iterable[str] | None = None,
        sensitivity: str | Sequence[str] | None = None,
        active_only: bool = True,
        user: Any = None,
        limit: int | None = None,
    ) -> list[MemoryGraphFact]:
        queryset = _base_fact_queryset(active_only=active_only)
        queryset = _filter_exact_or_in(queryset, "subject_id", subject_id)
        queryset = _filter_exact_or_in(queryset, "predicate", predicate)
        queryset = _filter_exact_or_in(queryset, "object_id", object_id)
        queryset = _filter_exact_or_in(queryset, "sensitivity", sensitivity)

        return _materialize_policy_checked(
            queryset,
            scope_tokens=scope_tokens,
            user=user,
            limit=limit,
        )

    def search_facts(
        self,
        query: str,
        *,
        scope_tokens: str | Iterable[str] | None = None,
        sensitivity: str | Sequence[str] | None = None,
        active_only: bool = True,
        user: Any = None,
        limit: int | None = 100,
    ) -> list[MemoryGraphFact]:
        queryset = _base_fact_queryset(active_only=active_only)
        queryset = _filter_exact_or_in(queryset, "sensitivity", sensitivity)

        query = (query or "").strip()
        if query:
            queryset = queryset.filter(
                Q(subject_id__icontains=query)
                | Q(predicate__icontains=query)
                | Q(object_id__icontains=query)
                | Q(subject_type__icontains=query)
                | Q(object_type__icontains=query)
            )

        return _materialize_policy_checked(
            queryset,
            scope_tokens=scope_tokens,
            user=user,
            limit=limit,
        )


class KuzuGraphMemoryBackend:
    """Placeholder for a future Kuzu-backed graph index.

    The import is deliberately lazy so Django can start without the optional
    dependency. Django remains the authority for policy, audit, and provenance.
    """

    def __init__(self, database_path: str):
        self.database_path = database_path

    def upsert_facts(self, facts: Iterable[GraphFactRecord | Mapping[str, Any]]) -> GraphFactUpsertResult:
        self._raise_placeholder()

    def deactivate_facts(
        self,
        *,
        snapshot: MemorySnapshot | None = None,
        snapshot_id: int | None = None,
        fact_ids: Iterable[str] | None = None,
        valid_to: Any = None,
    ) -> int:
        self._raise_placeholder()

    def filter_facts(
        self,
        *,
        subject_id: str | Sequence[str] | None = None,
        predicate: str | Sequence[str] | None = None,
        object_id: str | Sequence[str] | None = None,
        scope_tokens: str | Iterable[str] | None = None,
        sensitivity: str | Sequence[str] | None = None,
        active_only: bool = True,
        user: Any = None,
        limit: int | None = None,
    ) -> list[MemoryGraphFact]:
        self._raise_placeholder()

    def search_facts(
        self,
        query: str,
        *,
        scope_tokens: str | Iterable[str] | None = None,
        sensitivity: str | Sequence[str] | None = None,
        active_only: bool = True,
        user: Any = None,
        limit: int | None = 100,
    ) -> list[MemoryGraphFact]:
        self._raise_placeholder()

    def _raise_placeholder(self) -> NoReturn:
        try:
            import kuzu  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "KuzuGraphMemoryBackend requires the optional 'kuzu' package. "
                "Use DjangoGraphMemoryBackend or add the dependency before enabling Kuzu."
            ) from exc

        raise RuntimeError(
            "KuzuGraphMemoryBackend is a placeholder. The Kuzu index adapter is not implemented yet; "
            "use DjangoGraphMemoryBackend as the policy-authoritative graph backend."
        )


def _coerce_fact_record(value: GraphFactRecord | Mapping[str, Any]) -> GraphFactRecord:
    if isinstance(value, GraphFactRecord):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("Graph facts must be GraphFactRecord instances or mappings.")

    payload = dict(value)
    if "object" in payload and "object_id" not in payload:
        payload["object_id"] = payload.pop("object")

    source_chunk_id = payload.pop("source_chunk_id", None)
    if source_chunk_id is not None:
        if isinstance(source_chunk_id, int):
            payload.setdefault("source_chunk_pk", source_chunk_id)
        else:
            payload.setdefault("chunk_id", source_chunk_id)

    return GraphFactRecord(**payload)


def _resolve_source_chunk(fact: GraphFactRecord) -> MemoryChunk:
    if fact.source_chunk is not None:
        return fact.source_chunk
    if fact.source_chunk_pk is not None:
        return MemoryChunk.objects.select_related("snapshot", "snapshot__source").get(pk=fact.source_chunk_pk)
    if fact.chunk_id:
        return MemoryChunk.objects.select_related("snapshot", "snapshot__source").get(chunk_id=fact.chunk_id)
    raise ValueError("Graph facts must include source_chunk, source_chunk_pk, or chunk_id provenance.")


def _validate_provenance(*, fact: GraphFactRecord, source_chunk: MemoryChunk, snapshot: MemorySnapshot) -> None:
    if fact.snapshot is not None and fact.snapshot.pk != snapshot.pk:
        raise ValueError("Graph fact snapshot does not match the source chunk snapshot.")
    if fact.snapshot_id is not None and fact.snapshot_id != snapshot.pk:
        raise ValueError("Graph fact snapshot_id does not match the source chunk snapshot.")
    if snapshot.status != MemorySnapshot.Status.READY:
        raise ValueError("Graph facts can only be indexed from READY memory snapshots.")
    if not source_chunk.is_active:
        raise ValueError("Graph facts can only be indexed from active safe memory chunks.")


def _build_fact_defaults(
    *,
    fact: GraphFactRecord,
    source_chunk: MemoryChunk,
    snapshot: MemorySnapshot,
) -> dict[str, Any]:
    scope_tokens = list(fact.scope_tokens) if fact.scope_tokens is not None else list(source_chunk.scope_tokens or [])

    return {
        "source_chunk": source_chunk,
        "snapshot": snapshot,
        "snapshot_hash": fact.snapshot_hash or source_chunk.snapshot_hash or snapshot.content_hash,
        "subject_id": fact.subject_id,
        "predicate": fact.predicate,
        "object_id": fact.object_id,
        "subject_type": fact.subject_type,
        "object_type": fact.object_type,
        "confidence": _normalize_confidence(fact.confidence),
        "extracted_by": fact.extracted_by,
        "metadata": dict(fact.metadata or {}),
        "scope_tokens": scope_tokens,
        "sensitivity": fact.sensitivity or source_chunk.sensitivity or snapshot.sensitivity,
        "valid_from": fact.valid_from if fact.valid_from is not None else source_chunk.valid_from,
        "valid_to": fact.valid_to,
        "is_active": fact.is_active,
    }


def _normalize_confidence(value: Decimal | float | int | str) -> Decimal:
    try:
        confidence = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Graph fact confidence must be a number between 0 and 1.") from exc

    if confidence < 0 or confidence > 1:
        raise ValueError("Graph fact confidence must be between 0 and 1.")
    return confidence


def _base_fact_queryset(*, active_only: bool) -> QuerySet[MemoryGraphFact]:
    queryset = MemoryGraphFact.objects.select_related("source_chunk", "snapshot", "snapshot__source")
    if active_only:
        queryset = queryset.filter(is_active=True)
    return queryset


def _filter_exact_or_in(
    queryset: QuerySet[MemoryGraphFact],
    field_name: str,
    value: str | Sequence[str] | None,
) -> QuerySet[MemoryGraphFact]:
    if value is None:
        return queryset
    if isinstance(value, str):
        return queryset.filter(**{field_name: value})

    values = list(value)
    if not values:
        return queryset.none()
    return queryset.filter(**{f"{field_name}__in": values})


def _materialize_policy_checked(
    queryset: QuerySet[MemoryGraphFact],
    *,
    scope_tokens: str | Iterable[str] | None,
    user: Any,
    limit: int | None,
) -> list[MemoryGraphFact]:
    requested_scope_tokens = _normalize_scope_tokens(scope_tokens)
    records: list[MemoryGraphFact] = []

    for fact in queryset:
        if requested_scope_tokens is not None and not scope_tokens_match(fact.scope_tokens, requested_scope_tokens):
            continue
        if user is not None and not can_access_graph_fact(user, fact):
            continue
        records.append(fact)
        if limit is not None and len(records) >= limit:
            break

    return records


def _normalize_scope_tokens(scope_tokens: str | Iterable[str] | None) -> set[str] | None:
    if scope_tokens is None:
        return None
    if isinstance(scope_tokens, str):
        return {scope_tokens}
    return set(scope_tokens)


__all__ = [
    "DjangoGraphMemoryBackend",
    "GraphFactRecord",
    "GraphFactUpsertResult",
    "GraphMemoryBackend",
    "KuzuGraphMemoryBackend",
]
