from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


SQLITE_FTS_INDEX_RELATIVE_PATH = Path("memory") / "indexes" / "sqlite_fts" / "memory_fts.sqlite3"
DEFAULT_SEARCH_LIMIT = 10
MAX_FALLBACK_CANDIDATES = 1000


@dataclass(frozen=True)
class MemoryIndexRecord:
    chunk_id: str
    text: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    scope_tokens: Sequence[str] = field(default_factory=tuple)
    sensitivity: str = ""
    is_active: bool = True
    embedding: Sequence[float] | None = None


@dataclass(frozen=True)
class MemorySearchResult:
    chunk_id: str
    score: float
    metadata: dict[str, Any]


@runtime_checkable
class VectorMemoryBackend(Protocol):
    def upsert(self, record: MemoryIndexRecord) -> None:
        """Insert or replace one indexed chunk by its stable chunk_id."""

    def upsert_many(self, records: Iterable[MemoryIndexRecord]) -> int:
        """Insert or replace many indexed chunks and return the number processed."""

    def delete(self, chunk_ids: Iterable[str]) -> int:
        """Remove indexed chunks by chunk_id and return the number of ids processed."""

    def deactivate(self, chunk_ids: Iterable[str]) -> int:
        """Mark chunks inactive by chunk_id and remove them from the searchable FTS table."""

    def search(
        self,
        query: str,
        scope_tokens: Iterable[str] | None = None,
        sensitivity: str | Iterable[str] | None = None,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> list[MemorySearchResult]:
        """Return chunk ids, backend scores, and metadata for matching active chunks."""


class SQLiteFTSMemoryBackend:
    """Embedded full-text backend for the first memory indexing slice.

    SQLite FTS5 is used when the Python sqlite3 build supports it. If the
    extension is unavailable, the same API falls back to a conservative LIKE
    search over the indexed text table.
    """

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path is not None else default_sqlite_fts_index_path()
        self._schema_ready = False
        self._fts_enabled: bool | None = None

    def upsert(self, record: MemoryIndexRecord) -> None:
        self.upsert_many((record,))

    def upsert_many(self, records: Iterable[MemoryIndexRecord]) -> int:
        prepared_records = [_prepare_record(record) for record in records]
        if not prepared_records:
            return 0

        with self._connection() as connection:
            fts_enabled = self._has_fts(connection)
            with connection:
                for record in prepared_records:
                    connection.execute(
                        """
                        INSERT INTO memory_chunks (
                            chunk_id,
                            body,
                            metadata_json,
                            scope_tokens_json,
                            sensitivity,
                            is_active,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(chunk_id) DO UPDATE SET
                            body = excluded.body,
                            metadata_json = excluded.metadata_json,
                            scope_tokens_json = excluded.scope_tokens_json,
                            sensitivity = excluded.sensitivity,
                            is_active = excluded.is_active,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (
                            record.chunk_id,
                            record.text,
                            json.dumps(record.metadata, ensure_ascii=False, sort_keys=True),
                            json.dumps(record.scope_tokens, ensure_ascii=False),
                            record.sensitivity,
                            1 if record.is_active else 0,
                        ),
                    )
                    row = connection.execute(
                        "SELECT id FROM memory_chunks WHERE chunk_id = ?",
                        (record.chunk_id,),
                    ).fetchone()
                    if fts_enabled and row is not None:
                        self._delete_fts_row(connection, row["id"])
                        if record.is_active:
                            connection.execute(
                                "INSERT INTO memory_chunks_fts(rowid, chunk_id, body) VALUES (?, ?, ?)",
                                (row["id"], record.chunk_id, record.text),
                            )
        return len(prepared_records)

    def delete(self, chunk_ids: Iterable[str]) -> int:
        ids = _normalise_chunk_ids(chunk_ids)
        if not ids:
            return 0

        with self._connection() as connection:
            fts_enabled = self._has_fts(connection)
            with connection:
                if fts_enabled:
                    for row in self._rows_for_chunk_ids(connection, ids):
                        self._delete_fts_row(connection, row["id"])
                connection.executemany("DELETE FROM memory_chunks WHERE chunk_id = ?", ((chunk_id,) for chunk_id in ids))
        return len(ids)

    def deactivate(self, chunk_ids: Iterable[str]) -> int:
        ids = _normalise_chunk_ids(chunk_ids)
        if not ids:
            return 0

        with self._connection() as connection:
            fts_enabled = self._has_fts(connection)
            with connection:
                if fts_enabled:
                    for row in self._rows_for_chunk_ids(connection, ids):
                        self._delete_fts_row(connection, row["id"])
                connection.executemany(
                    """
                    UPDATE memory_chunks
                    SET is_active = 0, updated_at = CURRENT_TIMESTAMP
                    WHERE chunk_id = ?
                    """,
                    ((chunk_id,) for chunk_id in ids),
                )
        return len(ids)

    def search(
        self,
        query: str,
        scope_tokens: Iterable[str] | None = None,
        sensitivity: str | Iterable[str] | None = None,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> list[MemorySearchResult]:
        query = (query or "").strip()
        limit = _normalise_limit(limit)
        allowed_scope_tokens = _normalise_scope_filter(scope_tokens)
        allowed_sensitivities = _normalise_sensitivity_filter(sensitivity)

        if not query or limit <= 0:
            return []
        if allowed_scope_tokens == set():
            return []

        with self._connection() as connection:
            if self._has_fts(connection):
                try:
                    rows = self._search_fts(
                        connection,
                        query=query,
                        allowed_sensitivities=allowed_sensitivities,
                        fetch_limit=_candidate_fetch_limit(limit, allowed_scope_tokens),
                    )
                except sqlite3.Error:
                    rows = self._search_like(
                        connection,
                        query=query,
                        allowed_sensitivities=allowed_sensitivities,
                    )
            else:
                rows = self._search_like(
                    connection,
                    query=query,
                    allowed_sensitivities=allowed_sensitivities,
                )

        results = []
        terms = _query_terms(query)
        for row in rows:
            scope = _load_json_list(row["scope_tokens_json"])
            if not _scope_matches(scope, allowed_scope_tokens):
                continue
            score = float(row["score"]) if row["score"] is not None else _like_score(row["body"], terms)
            results.append(
                MemorySearchResult(
                    chunk_id=row["chunk_id"],
                    score=score,
                    metadata=_result_metadata(row["metadata_json"], scope, row["sensitivity"]),
                )
            )
            if len(results) >= limit:
                break
        return results

    def _search_fts(
        self,
        connection: sqlite3.Connection,
        *,
        query: str,
        allowed_sensitivities: set[str] | None,
        fetch_limit: int,
    ) -> list[sqlite3.Row]:
        fts_query = _fts_query(query)
        if not fts_query:
            return self._search_like(
                connection,
                query=query,
                allowed_sensitivities=allowed_sensitivities,
            )

        sensitivity_sql, sensitivity_params = _sensitivity_clause(allowed_sensitivities, column="c.sensitivity")
        return list(
            connection.execute(
                f"""
                SELECT
                    c.chunk_id,
                    c.body,
                    c.metadata_json,
                    c.scope_tokens_json,
                    c.sensitivity,
                    -bm25(memory_chunks_fts) AS score
                FROM memory_chunks_fts
                JOIN memory_chunks c ON c.id = memory_chunks_fts.rowid
                WHERE memory_chunks_fts MATCH ?
                  AND c.is_active = 1
                  {sensitivity_sql}
                ORDER BY score DESC, c.id ASC
                LIMIT ?
                """,
                (fts_query, *sensitivity_params, fetch_limit),
            )
        )

    def _search_like(
        self,
        connection: sqlite3.Connection,
        *,
        query: str,
        allowed_sensitivities: set[str] | None,
    ) -> list[sqlite3.Row]:
        terms = _query_terms(query) or [query]
        like_sql = " AND ".join("body LIKE ? ESCAPE '\\'" for _ in terms)
        like_params = [_like_pattern(term) for term in terms]
        sensitivity_sql, sensitivity_params = _sensitivity_clause(allowed_sensitivities, column="sensitivity")
        return list(
            connection.execute(
                f"""
                SELECT
                    chunk_id,
                    body,
                    metadata_json,
                    scope_tokens_json,
                    sensitivity,
                    NULL AS score
                FROM memory_chunks
                WHERE is_active = 1
                  AND {like_sql}
                  {sensitivity_sql}
                ORDER BY id ASC
                LIMIT ?
                """,
                (*like_params, *sensitivity_params, MAX_FALLBACK_CANDIDATES),
            )
        )

    @contextmanager
    def _connection(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            self._ensure_schema(connection)
            yield connection
        finally:
            connection.close()

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        if self._schema_ready:
            return

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_id TEXT NOT NULL UNIQUE,
                body TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                scope_tokens_json TEXT NOT NULL DEFAULT '[]',
                sensitivity TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS memory_chunks_active_idx ON memory_chunks(is_active)")
        connection.execute("CREATE INDEX IF NOT EXISTS memory_chunks_sensitivity_idx ON memory_chunks(sensitivity)")

        try:
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_chunks_fts
                USING fts5(chunk_id UNINDEXED, body, tokenize='unicode61')
                """
            )
        except sqlite3.Error:
            self._fts_enabled = False
        else:
            self._fts_enabled = True
            connection.execute(
                """
                INSERT INTO memory_chunks_fts(rowid, chunk_id, body)
                SELECT c.id, c.chunk_id, c.body
                FROM memory_chunks c
                WHERE c.is_active = 1
                  AND NOT EXISTS (
                    SELECT 1 FROM memory_chunks_fts f WHERE f.rowid = c.id
                  )
                """
            )
        connection.commit()
        self._schema_ready = True

    def _has_fts(self, connection: sqlite3.Connection) -> bool:
        if self._fts_enabled is not None:
            return self._fts_enabled
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'memory_chunks_fts'"
        ).fetchone()
        self._fts_enabled = row is not None
        return self._fts_enabled

    def _rows_for_chunk_ids(self, connection: sqlite3.Connection, chunk_ids: Sequence[str]) -> list[sqlite3.Row]:
        placeholders = ",".join("?" for _ in chunk_ids)
        return list(connection.execute(f"SELECT id FROM memory_chunks WHERE chunk_id IN ({placeholders})", chunk_ids))

    def _delete_fts_row(self, connection: sqlite3.Connection, row_id: int) -> None:
        connection.execute("DELETE FROM memory_chunks_fts WHERE rowid = ?", (row_id,))


def default_sqlite_fts_index_path() -> Path:
    data_dir = _django_data_dir()
    if data_dir is None:
        data_dir = Path.cwd() / "data"
    return data_dir / SQLITE_FTS_INDEX_RELATIVE_PATH


def get_default_backend() -> SQLiteFTSMemoryBackend:
    return SQLiteFTSMemoryBackend()


def _django_data_dir() -> Path | None:
    try:
        from django.conf import settings

        return Path(settings.DATA_DIR)
    except Exception:
        return None


def _prepare_record(record: MemoryIndexRecord) -> MemoryIndexRecord:
    chunk_id = (record.chunk_id or "").strip()
    if not chunk_id:
        raise ValueError("chunk_id is required")
    return MemoryIndexRecord(
        chunk_id=chunk_id,
        text=record.text or "",
        metadata=dict(record.metadata or {}),
        scope_tokens=tuple(_normalise_tokens(record.scope_tokens)),
        sensitivity=(record.sensitivity or "").strip(),
        is_active=bool(record.is_active),
        embedding=record.embedding,
    )


def _normalise_chunk_ids(chunk_ids: Iterable[str]) -> tuple[str, ...]:
    seen = set()
    ids = []
    for chunk_id in chunk_ids:
        value = (chunk_id or "").strip()
        if value and value not in seen:
            seen.add(value)
            ids.append(value)
    return tuple(ids)


def _normalise_tokens(tokens: Iterable[str] | str | None) -> tuple[str, ...]:
    if tokens is None:
        return ()
    if isinstance(tokens, str):
        tokens = (tokens,)
    seen = set()
    values = []
    for token in tokens:
        value = str(token or "").strip()
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return tuple(values)


def _normalise_scope_filter(scope_tokens: Iterable[str] | None) -> set[str] | None:
    if scope_tokens is None:
        return None
    return set(_normalise_tokens(scope_tokens))


def _normalise_sensitivity_filter(sensitivity: str | Iterable[str] | None) -> set[str] | None:
    if sensitivity is None:
        return None
    return set(_normalise_tokens(sensitivity))


def _normalise_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return DEFAULT_SEARCH_LIMIT
    return max(0, value)


def _candidate_fetch_limit(limit: int, allowed_scope_tokens: set[str] | None) -> int:
    if allowed_scope_tokens is None:
        return limit
    return min(max(limit * 50, limit, 50), MAX_FALLBACK_CANDIDATES)


def _scope_matches(required_tokens: Sequence[str], allowed_tokens: set[str] | None) -> bool:
    if allowed_tokens is None:
        return True
    if not required_tokens:
        return False
    return bool(set(required_tokens) & allowed_tokens)


def _sensitivity_clause(allowed_sensitivities: set[str] | None, *, column: str) -> tuple[str, tuple[str, ...]]:
    if allowed_sensitivities is None:
        return "", ()
    if not allowed_sensitivities:
        return "AND 0", ()
    placeholders = ",".join("?" for _ in allowed_sensitivities)
    return f"AND {column} IN ({placeholders})", tuple(sorted(allowed_sensitivities))


def _query_terms(query: str) -> list[str]:
    return re.findall(r"[\w]+", query, flags=re.UNICODE)


def _fts_query(query: str) -> str:
    terms = _query_terms(query)
    if not terms:
        return ""
    return " AND ".join(f'"{term.replace(chr(34), chr(34) + chr(34))}"' for term in terms[:16])


def _like_pattern(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _like_score(body: str, terms: Sequence[str]) -> float:
    text = (body or "").lower()
    if not text:
        return 0.0
    if not terms:
        return 0.0
    matches = sum(text.count(term.lower()) for term in terms if term)
    return matches / max(len(text), 1)


def _load_json_list(value: str) -> list[str]:
    try:
        payload = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [str(item) for item in payload if str(item or "").strip()]


def _result_metadata(metadata_json: str, scope_tokens: Sequence[str], sensitivity: str) -> dict[str, Any]:
    try:
        metadata = json.loads(metadata_json or "{}")
    except json.JSONDecodeError:
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    metadata.setdefault("scope_tokens", list(scope_tokens))
    metadata.setdefault("sensitivity", sensitivity)
    return metadata


__all__ = [
    "DEFAULT_SEARCH_LIMIT",
    "MAX_FALLBACK_CANDIDATES",
    "MemoryIndexRecord",
    "MemorySearchResult",
    "SQLITE_FTS_INDEX_RELATIVE_PATH",
    "SQLiteFTSMemoryBackend",
    "VectorMemoryBackend",
    "default_sqlite_fts_index_path",
    "get_default_backend",
]
