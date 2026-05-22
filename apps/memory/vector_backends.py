from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


SQLITE_FTS_INDEX_RELATIVE_PATH = Path("indexes") / "fulltext" / "search.sqlite3"
DEFAULT_SEARCH_LIMIT = 10
MAX_FALLBACK_CANDIDATES = 1000


@dataclass(frozen=True, init=False)
class MemoryIndexRecord:
    document_id: str
    text: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    scope_tokens: Sequence[str] = field(default_factory=tuple)
    sensitivity: str = ""
    is_active: bool = True
    embedding: Sequence[float] | None = None

    def __init__(
        self,
        document_id: str = "",
        text: str = "",
        metadata: Mapping[str, Any] | None = None,
        scope_tokens: Sequence[str] = (),
        sensitivity: str = "",
        is_active: bool = True,
        embedding: Sequence[float] | None = None,
    ):
        object.__setattr__(self, "document_id", document_id)
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "metadata", metadata or {})
        object.__setattr__(self, "scope_tokens", scope_tokens)
        object.__setattr__(self, "sensitivity", sensitivity)
        object.__setattr__(self, "is_active", is_active)
        object.__setattr__(self, "embedding", embedding)


@dataclass(frozen=True, init=False)
class MemorySearchResult:
    document_id: str
    score: float
    metadata: dict[str, Any]

    def __init__(self, document_id: str = "", score: float = 0.0, metadata: dict[str, Any] | None = None):
        object.__setattr__(self, "document_id", document_id)
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "metadata", metadata or {})


@runtime_checkable
class VectorMemoryBackend(Protocol):
    def upsert(self, record: MemoryIndexRecord) -> None:
        """Insert or replace one indexed document by its stable document_id."""

    def upsert_many(self, records: Iterable[MemoryIndexRecord]) -> int:
        """Insert or replace many indexed documents and return the number processed."""

    def delete(self, document_ids: Iterable[str]) -> int:
        """Remove indexed documents by document_id and return the number of ids processed."""

    def deactivate(self, document_ids: Iterable[str]) -> int:
        """Mark documents inactive by document_id and remove them from the searchable FTS table."""

    def search(
        self,
        query: str,
        scope_tokens: Iterable[str] | None = None,
        sensitivity: str | Iterable[str] | None = None,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> list[MemorySearchResult]:
        """Return document ids, backend scores, and metadata for matching active documents."""


class SQLiteFTSMemoryBackend:
    """Embedded SQLite search backend for the first memory indexing slice.

    The backend stores document ids, metadata and derived search tokens. It
    does not store retrievable full knowledge text; readers load that text
    from the knowledge file.
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
                        INSERT INTO memory_documents (
                            document_id,
                            metadata_json,
                            scope_tokens_json,
                            sensitivity,
                            is_active,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(document_id) DO UPDATE SET
                            metadata_json = excluded.metadata_json,
                            scope_tokens_json = excluded.scope_tokens_json,
                            sensitivity = excluded.sensitivity,
                            is_active = excluded.is_active,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (
                            record.document_id,
                            json.dumps(record.metadata, ensure_ascii=False, sort_keys=True),
                            json.dumps(record.scope_tokens, ensure_ascii=False),
                            record.sensitivity,
                            1 if record.is_active else 0,
                        ),
                    )
                    row = connection.execute(
                        "SELECT id FROM memory_documents WHERE document_id = ?",
                        (record.document_id,),
                    ).fetchone()
                    if fts_enabled and row is not None:
                        self._delete_fts_row(connection, row["id"])
                        if record.is_active:
                            connection.execute(
                                "INSERT INTO memory_documents_fts(rowid, document_id, body) VALUES (?, ?, ?)",
                                (row["id"], record.document_id, record.text),
                            )
                    if row is not None:
                        connection.execute("DELETE FROM memory_document_terms WHERE document_row_id = ?", (row["id"],))
                        if record.is_active:
                            connection.executemany(
                                "INSERT OR IGNORE INTO memory_document_terms(document_row_id, token) VALUES (?, ?)",
                                ((row["id"], token) for token in _unique_terms(record.text)),
                            )
        return len(prepared_records)

    def delete(self, document_ids: Iterable[str]) -> int:
        ids = _normalise_document_ids(document_ids)
        if not ids:
            return 0

        with self._connection() as connection:
            fts_enabled = self._has_fts(connection)
            with connection:
                if fts_enabled:
                    for row in self._rows_for_document_ids(connection, ids):
                        self._delete_fts_row(connection, row["id"])
                for row in self._rows_for_document_ids(connection, ids):
                    connection.execute("DELETE FROM memory_document_terms WHERE document_row_id = ?", (row["id"],))
                connection.executemany("DELETE FROM memory_documents WHERE document_id = ?", ((document_id,) for document_id in ids))
        return len(ids)

    def deactivate(self, document_ids: Iterable[str]) -> int:
        ids = _normalise_document_ids(document_ids)
        if not ids:
            return 0

        with self._connection() as connection:
            fts_enabled = self._has_fts(connection)
            with connection:
                if fts_enabled:
                    for row in self._rows_for_document_ids(connection, ids):
                        self._delete_fts_row(connection, row["id"])
                for row in self._rows_for_document_ids(connection, ids):
                    connection.execute("DELETE FROM memory_document_terms WHERE document_row_id = ?", (row["id"],))
                connection.executemany(
                    """
                    UPDATE memory_documents
                    SET is_active = 0, updated_at = CURRENT_TIMESTAMP
                    WHERE document_id = ?
                    """,
                    ((document_id,) for document_id in ids),
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
                    rows = self._search_terms(
                        connection,
                        query=query,
                        allowed_sensitivities=allowed_sensitivities,
                    )
            else:
                rows = self._search_terms(
                    connection,
                    query=query,
                    allowed_sensitivities=allowed_sensitivities,
                )

        results = []
        for row in rows:
            scope = _load_json_list(row["scope_tokens_json"])
            if not _scope_matches(scope, allowed_scope_tokens):
                continue
            score = float(row["score"]) if row["score"] is not None else 0.0
            results.append(
                MemorySearchResult(
                    document_id=row["document_id"],
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
            return self._search_terms(
                connection,
                query=query,
                allowed_sensitivities=allowed_sensitivities,
            )

        sensitivity_sql, sensitivity_params = _sensitivity_clause(allowed_sensitivities, column="c.sensitivity")
        return list(
            connection.execute(
                f"""
                SELECT
                    c.document_id,
                    c.metadata_json,
                    c.scope_tokens_json,
                    c.sensitivity,
                    -bm25(memory_documents_fts) AS score
                FROM memory_documents_fts
                JOIN memory_documents c ON c.id = memory_documents_fts.rowid
                WHERE memory_documents_fts MATCH ?
                  AND c.is_active = 1
                  {sensitivity_sql}
                ORDER BY score DESC, c.id ASC
                LIMIT ?
                """,
                (fts_query, *sensitivity_params, fetch_limit),
            )
        )

    def _search_terms(
        self,
        connection: sqlite3.Connection,
        *,
        query: str,
        allowed_sensitivities: set[str] | None,
    ) -> list[sqlite3.Row]:
        terms = _query_terms(query) or [query]
        terms = tuple(_unique_terms(" ".join(terms)))
        if not terms:
            return []
        placeholders = ",".join("?" for _ in terms)
        sensitivity_sql, sensitivity_params = _sensitivity_clause(allowed_sensitivities, column="sensitivity")
        return list(
            connection.execute(
                f"""
                SELECT
                    c.document_id,
                    c.metadata_json,
                    c.scope_tokens_json,
                    c.sensitivity,
                    CAST(COUNT(DISTINCT t.token) AS REAL) / ? AS score
                FROM memory_documents c
                JOIN memory_document_terms t ON t.document_row_id = c.id
                WHERE c.is_active = 1
                  AND t.token IN ({placeholders})
                  {sensitivity_sql}
                GROUP BY c.id
                HAVING COUNT(DISTINCT t.token) = ?
                ORDER BY score DESC, c.id ASC
                LIMIT ?
                """,
                (len(terms), *terms, *sensitivity_params, len(terms), MAX_FALLBACK_CANDIDATES),
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
        self._drop_legacy_body_schema(connection)

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL UNIQUE,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                scope_tokens_json TEXT NOT NULL DEFAULT '[]',
                sensitivity TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS memory_documents_active_idx ON memory_documents(is_active)")
        connection.execute("CREATE INDEX IF NOT EXISTS memory_documents_sensitivity_idx ON memory_documents(sensitivity)")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_document_terms (
                document_row_id INTEGER NOT NULL,
                token TEXT NOT NULL,
                PRIMARY KEY (document_row_id, token),
                FOREIGN KEY(document_row_id) REFERENCES memory_documents(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS memory_document_terms_token_idx ON memory_document_terms(token)")

        connection.execute("DROP TABLE IF EXISTS memory_documents_fts")
        self._fts_enabled = False
        connection.commit()
        self._schema_ready = True

    def _drop_legacy_body_schema(self, connection: sqlite3.Connection) -> None:
        row = connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'memory_documents'").fetchone()
        if row is None:
            return
        columns = [item["name"] for item in connection.execute("PRAGMA table_info(memory_documents)").fetchall()]
        if "body" not in columns:
            return
        connection.execute("DROP TABLE IF EXISTS memory_documents_fts")
        connection.execute("DROP TABLE IF EXISTS memory_document_terms")
        connection.execute("DROP TABLE IF EXISTS memory_documents")

    def _has_fts(self, connection: sqlite3.Connection) -> bool:
        return False

    def _rows_for_document_ids(self, connection: sqlite3.Connection, document_ids: Sequence[str]) -> list[sqlite3.Row]:
        placeholders = ",".join("?" for _ in document_ids)
        return list(connection.execute(f"SELECT id FROM memory_documents WHERE document_id IN ({placeholders})", document_ids))

    def _delete_fts_row(self, connection: sqlite3.Connection, row_id: int) -> None:
        connection.execute("DELETE FROM memory_documents_fts WHERE rowid = ?", (row_id,))


def default_sqlite_fts_index_path() -> Path:
    configured = _django_search_index_path()
    if configured is not None:
        return configured
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


def _django_search_index_path() -> Path | None:
    try:
        import os

        from django.conf import settings

        override = os.environ.get("LOCAL_BUSINESS_SEARCH_INDEX_PATH", "").strip()
        if override:
            return Path(override)
        return Path(settings.DATA_DIR) / SQLITE_FTS_INDEX_RELATIVE_PATH
    except Exception:
        return None


def _prepare_record(record: MemoryIndexRecord) -> MemoryIndexRecord:
    document_id = (record.document_id or "").strip()
    if not document_id:
        raise ValueError("document_id is required")
    return MemoryIndexRecord(
        document_id=document_id,
        text=record.text or "",
        metadata=dict(record.metadata or {}),
        scope_tokens=tuple(_normalise_tokens(record.scope_tokens)),
        sensitivity=(record.sensitivity or "").strip(),
        is_active=bool(record.is_active),
        embedding=record.embedding,
    )


def _normalise_document_ids(document_ids: Iterable[str]) -> tuple[str, ...]:
    seen = set()
    ids = []
    for document_id in document_ids:
        value = (document_id or "").strip()
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


def _unique_terms(text: str) -> tuple[str, ...]:
    seen = set()
    terms = []
    for term in _query_terms(text):
        value = term.lower()
        if value not in seen:
            seen.add(value)
            terms.append(value)
    return tuple(terms)


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
