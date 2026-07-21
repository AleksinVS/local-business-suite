from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class GraphFactRecord:
    fact_id: str
    subject_id: str
    predicate: str
    object_id: str
    document_id: str = ""
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
    records: tuple[Any, ...]

    @property
    def fact_ids(self) -> tuple[str, ...]:
        return tuple(getattr(record, "fact_id", "") for record in self.records)


@runtime_checkable
class GraphMemoryBackend(Protocol):
    def upsert_facts(self, facts: Iterable[GraphFactRecord | Mapping[str, Any]]) -> GraphFactUpsertResult:
        """Create or update graph facts by stable fact_id."""
        ...

    def deactivate_facts(
        self,
        *,
        document_id: str | None = None,
        fact_ids: Iterable[str] | None = None,
        valid_to: Any = None,
    ) -> int:
        """Deactivate facts by document and/or fact_id."""
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
    ) -> list[Any]:
        """Search graph facts. Direct graph search is deferred until the graph index is redesigned."""
        ...


class DjangoGraphMemoryBackend:
    """Placeholder backend until the graph search strategy is designed separately."""

    def upsert_facts(self, facts: Iterable[GraphFactRecord | Mapping[str, Any]]) -> GraphFactUpsertResult:
        return GraphFactUpsertResult(created_count=0, updated_count=0, records=())

    def deactivate_facts(
        self,
        *,
        document_id: str | None = None,
        fact_ids: Iterable[str] | None = None,
        valid_to: Any = None,
    ) -> int:
        return 0

    def search_facts(
        self,
        query: str,
        *,
        scope_tokens: str | Iterable[str] | None = None,
        sensitivity: str | Sequence[str] | None = None,
        active_only: bool = True,
        user: Any = None,
        limit: int | None = 100,
    ) -> list[Any]:
        return []


class KuzuGraphMemoryBackend(DjangoGraphMemoryBackend):
    """Placeholder for a future Kuzu-backed graph index."""

    def __init__(self, database_path: str):
        self.database_path = database_path


__all__ = [
    "DjangoGraphMemoryBackend",
    "GraphFactRecord",
    "GraphFactUpsertResult",
    "GraphMemoryBackend",
    "KuzuGraphMemoryBackend",
]
