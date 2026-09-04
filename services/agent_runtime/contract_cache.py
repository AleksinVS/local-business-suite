"""Aggregate AI contract delivery with a bounded last-known-good cache.

The runtime never reads the migrated AI documents from a shared file volume.
One authenticated HTTP response is validated as a whole and committed as one
state transition.  A refresh performs network I/O outside the state lock;
single-flight prevents duplicate requests while a fresh LKG lets concurrent
callers proceed without waiting for a slow gateway.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from copy import deepcopy

import httpx

logger = logging.getLogger(__name__)

AI_DOCUMENT_IDS = (
    "ai.contract.registry",
    "ai.contract.tools",
    "ai.contract.task_types",
    "ai.contract.models",
    "ai.contract.chat_settings",
)
AI_DOCUMENT_ALLOWLIST = frozenset(AI_DOCUMENT_IDS)
AI_DOCUMENT_SCHEMA_VERSION = 1
DEFAULT_MAX_STALE_AGE_SECONDS = 300.0
MAX_STALE_AGE_SECONDS = DEFAULT_MAX_STALE_AGE_SECONDS
_STRONG_ETAG_RE = re.compile(r'^"[^"]+"$')


class ContractDeliveryError(RuntimeError):
    """The gateway response cannot safely replace the LKG snapshot."""


class ContractValidationError(ContractDeliveryError):
    pass


def canonical_json(value) -> str:
    def validate(item, seen):
        if item is None or isinstance(item, (str, bool, int)):
            return
        if isinstance(item, float):
            if item != item or item in (float("inf"), float("-inf")):
                raise ValueError("non-finite JSON number")
            return
        if isinstance(item, list):
            marker = id(item)
            if marker in seen:
                raise ValueError("cyclic JSON value")
            seen.add(marker)
            try:
                for child in item:
                    validate(child, seen)
            finally:
                seen.remove(marker)
            return
        if isinstance(item, dict):
            marker = id(item)
            if marker in seen:
                raise ValueError("cyclic JSON value")
            seen.add(marker)
            try:
                for key, child in item.items():
                    if not isinstance(key, str):
                        raise ValueError("non-string JSON key")
                    validate(child, seen)
            finally:
                seen.remove(marker)
            return
        raise ValueError("non-JSON value")

    validate(value, set())
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def content_hash(payload) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def aggregate_etag(documents) -> str:
    """Strong ETag over sorted ID/schema/revision/content-hash tuples."""
    entries = sorted(
        [
            str(item["document_id"]),
            int(item["schema_version"]),
            int(item["revision"]),
            str(item["content_hash"]),
        ]
        for item in documents
    )
    return '"' + content_hash(entries) + '"'


def _configured_stale_age(value=None) -> float:
    if value is not None:
        return max(float(value), 0.0)
    raw = os.environ.get(
        "LOCAL_BUSINESS_AI_CONTRACT_MAX_STALE_AGE_SECONDS",
        os.environ.get(
            "LOCAL_BUSINESS_AI_MAX_STALE_AGE_SECONDS",
            str(DEFAULT_MAX_STALE_AGE_SECONDS),
        ),
    )
    try:
        return max(float(raw), 0.0)
    except (TypeError, ValueError):
        return DEFAULT_MAX_STALE_AGE_SECONDS


def _error_code(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"http_{exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "gateway_timeout"
    if isinstance(exc, httpx.HTTPError):
        return "gateway_http_error"
    if isinstance(exc, ContractValidationError):
        return "invalid_gateway_snapshot"
    return "gateway_unavailable"


def _validate_envelope(payload, requested_ids, *, response_etag):
    if not isinstance(payload, dict):
        raise ContractValidationError("gateway response is not an object")
    raw_documents = payload.get("documents", payload.get("snapshot"))
    if not isinstance(raw_documents, list):
        raise ContractValidationError("gateway response has no aggregate documents")
    requested = tuple(sorted(str(item) for item in requested_ids))
    actual_ids = tuple(
        sorted(
            item.get("document_id")
            for item in raw_documents
            if isinstance(item, dict) and isinstance(item.get("document_id"), str)
        )
    )
    if actual_ids != requested or len(raw_documents) != len(requested):
        raise ContractValidationError("gateway response is not the exact requested set")

    documents = []
    seen = set()
    for item in raw_documents:
        if not isinstance(item, dict):
            raise ContractValidationError("document envelope must be an object")
        document_id = item.get("document_id")
        if (
            not isinstance(document_id, str)
            or document_id not in AI_DOCUMENT_ALLOWLIST
            or document_id in seen
        ):
            raise ContractValidationError("document is outside the allowlist")
        seen.add(document_id)
        if item.get("schema_version") != AI_DOCUMENT_SCHEMA_VERSION:
            raise ContractValidationError("unsupported document schema")
        if "payload" not in item:
            raise ContractValidationError("document payload is missing")
        supplied_hash = item.get("content_hash")
        if (
            not isinstance(supplied_hash, str)
            or len(supplied_hash) != 64
            or any(char not in "0123456789abcdef" for char in supplied_hash)
        ):
            raise ContractValidationError("invalid document hash")
        try:
            actual_hash = content_hash(item.get("payload"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ContractValidationError("payload is not canonical JSON") from exc
        if actual_hash != supplied_hash:
            raise ContractValidationError("document content hash mismatch")
        revision = item.get("revision")
        if type(revision) is not int or revision < 0:
            raise ContractValidationError("invalid document revision")
        documents.append(
            {
                "document_id": document_id,
                "schema_version": AI_DOCUMENT_SCHEMA_VERSION,
                "revision": revision,
                "content_hash": supplied_hash,
                "payload": deepcopy(item.get("payload")),
            }
        )

    documents.sort(key=lambda item: item["document_id"])
    computed_etag = aggregate_etag(documents)
    if not isinstance(response_etag, str) or not _STRONG_ETAG_RE.fullmatch(response_etag):
        raise ContractValidationError("missing or weak aggregate ETag")
    if response_etag != computed_etag:
        raise ContractValidationError("aggregate ETag mismatch")
    return {item["document_id"]: item for item in documents}, computed_etag


class AgentContractCache:
    """Thread-safe aggregate LKG cache with non-blocking fresh-LKG reads."""

    def __init__(
        self,
        *,
        gateway_url: str,
        token: str,
        requested_ids=AI_DOCUMENT_IDS,
        max_stale_age=None,
        client=None,
        clock=None,
    ):
        requested_ids = tuple(sorted(str(item) for item in requested_ids))
        if (
            not requested_ids
            or len(set(requested_ids)) != len(requested_ids)
            or not set(requested_ids).issubset(AI_DOCUMENT_ALLOWLIST)
        ):
            raise ValueError("requested_ids is invalid")
        self.gateway_url = gateway_url.rstrip("/")
        self.token = token
        self.requested_ids = requested_ids
        self.max_stale_age = _configured_stale_age(max_stale_age)
        self._client = client
        self._clock = clock or time.time
        self._state_lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._documents = None
        self._etag = None
        self._last_validated_at = None
        self._last_error = ""

    @property
    def url(self):
        return f"{self.gateway_url}/contracts/"

    @property
    def last_validated_at(self):
        with self._state_lock:
            return self._last_validated_at

    def _state_copy(self):
        with self._state_lock:
            return (
                deepcopy(self._documents) if self._documents is not None else None,
                self._etag,
                self._last_validated_at,
            )

    def _usable_lkg(self, documents, validated_at):
        if documents is None or validated_at is None:
            return False
        return max(0.0, self._clock() - validated_at) <= self.max_stale_age

    def _network_refresh(self, etag):
        headers = {"X-AI-Gateway-Token": self.token}
        if etag:
            headers["If-None-Match"] = etag
        close_client = self._client is None
        client = self._client or httpx.Client(timeout=10.0)
        try:
            response = client.get(
                self.url,
                params=[("ids", item) for item in self.requested_ids],
                headers=headers,
            )
        finally:
            if close_client:
                client.close()
        now = self._clock()
        if response.status_code == 304:
            response_etag = response.headers.get("ETag")
            if not etag or response_etag != etag or not _STRONG_ETAG_RE.fullmatch(response_etag or ""):
                raise ContractValidationError("304 ETag does not match current snapshot")
            return None, etag, now
        response.raise_for_status()
        documents, computed_etag = _validate_envelope(
            response.json(), self.requested_ids, response_etag=response.headers.get("ETag")
        )
        return documents, computed_etag, now

    def refresh(self):
        """Poll gateway; fresh-LKG callers do not wait behind another poll."""
        documents, etag, validated_at = self._state_copy()
        if self._refresh_lock.acquire(blocking=False):
            try:
                # Re-read state after acquiring the flight lock: another
                # request may have completed a refresh between the first read
                # and this acquisition.
                documents, etag, validated_at = self._state_copy()
                try:
                    new_documents, new_etag, now = self._network_refresh(etag)
                    with self._state_lock:
                        if new_documents is not None:
                            self._documents = new_documents
                            self._etag = new_etag
                        self._last_validated_at = now
                        self._last_error = ""
                        result = deepcopy(self._documents)
                    if result is None:
                        raise ContractDeliveryError("304 received before first valid snapshot")
                    return result
                except Exception as exc:  # noqa: BLE001 - fail-closed boundary
                    code = _error_code(exc)
                    with self._state_lock:
                        self._last_error = code
                        current_documents = deepcopy(self._documents)
                        current_validated_at = self._last_validated_at
                    logger.warning(
                        "AI contract gateway refresh failed: error_type=%s error_code=%s",
                        exc.__class__.__name__,
                        code,
                    )
                    if self._usable_lkg(current_documents, current_validated_at):
                        return current_documents
                    raise ContractDeliveryError("AI contract snapshot unavailable") from exc
            finally:
                self._refresh_lock.release()

        # A fresh LKG is intentionally returned immediately while the leader
        # performs network I/O.  With no usable snapshot, wait for the flight
        # to finish and then consume its result/error.
        if self._usable_lkg(documents, validated_at):
            return documents
        with self._refresh_lock:
            documents, _etag, validated_at = self._state_copy()
            if self._usable_lkg(documents, validated_at):
                return documents
            raise ContractDeliveryError("AI contract snapshot unavailable")

    fetch = refresh

    def snapshot(self):
        return self.refresh()

    get_snapshot = snapshot

    def get(self, document_id: str):
        if document_id not in self.requested_ids:
            raise KeyError(document_id)
        return self.snapshot()[document_id]

    def age(self):
        with self._state_lock:
            validated_at = self._last_validated_at
        if validated_at is None:
            # JSON has no useful representation for infinity.  ``None`` is a
            # bounded, explicit signal that no last-known-good snapshot exists.
            return None
        return max(0.0, self._clock() - validated_at)

    def diagnostics(self):
        with self._state_lock:
            documents = self._documents or {}
            error = self._last_error
            return {
                "source": ("lkg" if error else "gateway") if documents else "unavailable",
                "age": self.age(),
                "revisions": {key: value["revision"] for key, value in sorted(documents.items())},
                "hashes": {key: value["content_hash"] for key, value in sorted(documents.items())},
                "error": error,
            }

    get_diagnostics = diagnostics


_gateway_caches = {}
_gateway_caches_lock = threading.Lock()


def get_gateway_cache(*, gateway_url: str, token: str, requested_ids=AI_DOCUMENT_IDS):
    key = (gateway_url.rstrip("/"), token, tuple(sorted(requested_ids)))
    with _gateway_caches_lock:
        cache = _gateway_caches.get(key)
        if cache is None:
            cache = AgentContractCache(
                gateway_url=gateway_url,
                token=token,
                requested_ids=requested_ids,
            )
            _gateway_caches[key] = cache
        return cache


def load_gateway_snapshot(*, gateway_url, token, requested_ids=AI_DOCUMENT_IDS):
    return get_gateway_cache(
        gateway_url=gateway_url, token=token, requested_ids=requested_ids
    ).snapshot()


def load_gateway_document(document_id, *, gateway_url, token, snapshot=None):
    if snapshot is not None:
        return deepcopy(snapshot[document_id])
    return get_gateway_cache(gateway_url=gateway_url, token=token).get(document_id)


ContractSnapshotCache = AgentContractCache


def clear() -> None:
    with _gateway_caches_lock:
        _gateway_caches.clear()
