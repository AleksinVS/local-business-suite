"""Small in-process cache for agent-runtime contract JSON files.

Context (ADR-0031, "Доставка контрактов в agent-runtime — шаг 1"):
agent-runtime reads AI contracts (``tools.json``, ``task_types.json``,
``models.json``) from ``data/contracts/ai/`` (Settings Center working
copy) when available, falling back to the packaged default in
``contracts/ai/``. In Docker, the first compose start races Django,
which is the process that actually creates the working copy — the
agent can come up before it exists. Later edits made through Settings
Center must also reach the running agent without a restart.

This module keeps that behaviour cheap and correct:

- the cache key for a resolved path is ``(st_mtime_ns, st_size, st_ino)``,
  not a bare mtime — this mirrors the contract store invalidation key
  used on the Django side (ADR-0031), because an atomic ``os.replace``
  write changes inode and some filesystems only offer coarse mtime
  resolution;
- **path resolution itself is never cached here.** Callers must pass a
  freshly resolved ``Path`` (or something that resolves fresh, such as
  ``config._contract_path(...)`` called right before) on every call, so
  that a runtime copy created after process start — or removed later —
  is picked up on the very next read. Only the parsed JSON *content*
  behind a given resolved path is cached, keyed by ``str(path)`` plus
  the metadata tuple.

This is intentionally simpler than the Django-side contract store: it
has no per-request snapshot semantics, no "return last good value on
error" degradation signal, and no immutability guarantee on the
returned payload. Agent-runtime has no per-request framework hook to
attach a snapshot to, and its callers (``prompting.py``,
``mcp_server.py``) only read the payload, never mutate it.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import NamedTuple


class _CacheEntry(NamedTuple):
    stat_key: tuple[int, int, int]
    payload: object


_lock = threading.Lock()
_cache: dict[str, _CacheEntry] = {}


def _stat_key(path: Path) -> tuple[int, int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def load_json_cached(path: Path):
    """Return the parsed JSON payload for ``path``, reusing the cached
    parse when the file's ``(st_mtime_ns, st_size, st_ino)`` key is
    unchanged since the last read.

    ``path`` must already be the freshly resolved location (the caller
    is responsible for re-running path resolution, e.g. via
    ``config._contract_path``, on every call — see module docstring).
    Raises ``FileNotFoundError`` if the file does not exist, matching
    the previous uncached ``json.loads(path.read_text())`` behaviour.
    """
    cache_id = str(path)
    key = _stat_key(path)

    if key is not None:
        with _lock:
            entry = _cache.get(cache_id)
            if entry is not None and entry.stat_key == key:
                return entry.payload

    if key is None:
        # Surface a clear error instead of silently serving stale data
        # forever; this matches the previous uncached behaviour where a
        # missing file raised on every read.
        raise FileNotFoundError(f"Contract file not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    with _lock:
        _cache[cache_id] = _CacheEntry(stat_key=key, payload=payload)
    return payload


def clear() -> None:
    """Drop all cached entries. Test-only hook."""
    with _lock:
        _cache.clear()
