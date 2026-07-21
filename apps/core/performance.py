from __future__ import annotations

import json
import logging
import random
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)

PERFORMANCE_EVENT_SCHEMA_VERSION = "performance-event-v1"
HTTP_REQUEST_EVENT_TYPE = "http_request"


class PerformanceMetricsMiddleware:
    """Optionally records request latency events without user or payload data."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started_at = time.perf_counter()
        query_count_started_at = len(connection.queries)
        response = None
        try:
            response = self.get_response(request)
            return response
        finally:
            if (
                _performance_metrics_enabled()
                and _should_sample()
                and not _is_excluded_path(getattr(request, "path", ""))
            ):
                duration_ms = (time.perf_counter() - started_at) * 1000
                status_code = getattr(response, "status_code", 500)
                route_name, route_pattern = _safe_route_metadata(request)
                event = {
                    "schema_version": PERFORMANCE_EVENT_SCHEMA_VERSION,
                    "event_type": HTTP_REQUEST_EVENT_TYPE,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "method": getattr(request, "method", ""),
                    "route_name": route_name,
                    "route_pattern": route_pattern,
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 3),
                    "db_query_count": _db_query_count_since(query_count_started_at),
                }
                record_performance_event(event)


def record_performance_event(event: dict[str, Any], path: Path | str | None = None) -> None:
    target = Path(path) if path is not None else _performance_metrics_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    safe_event = _normalise_event(event)
    try:
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(safe_event, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    except OSError as exc:
        logger.warning("Could not write performance metric event: %s", exc)


def summarize_performance_events(
    path: Path | str | None = None,
    *,
    event_type: str = HTTP_REQUEST_EVENT_TYPE,
    group_by: str = "route_name",
    min_count: int = 1,
    top: int | None = None,
) -> list[dict[str, Any]]:
    target = Path(path) if path is not None else _performance_metrics_path()
    groups: dict[str, list[float]] = defaultdict(list)
    statuses: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for event in _iter_events(target):
        if event_type and event.get("event_type") != event_type:
            continue
        duration = _duration_ms(event)
        if duration is None:
            continue
        group_key = _group_key(event, group_by)
        groups[group_key].append(duration)
        status_code = str(event.get("status_code") or "unknown")
        statuses[group_key][status_code] += 1

    rows: list[dict[str, Any]] = []
    for key, durations in groups.items():
        if len(durations) < min_count:
            continue
        ordered = sorted(durations)
        rows.append(
            {
                "group": key,
                "count": len(ordered),
                "p50_ms": _nearest_rank_percentile(ordered, 50),
                "p95_ms": _nearest_rank_percentile(ordered, 95),
                "max_ms": round(ordered[-1], 3),
                "status_codes": dict(sorted(statuses[key].items())),
            }
        )

    rows.sort(key=lambda item: (item["p95_ms"], item["count"]), reverse=True)
    if top is not None:
        rows = rows[:top]
    return rows


def _performance_metrics_enabled() -> bool:
    return bool(getattr(settings, "LOCAL_BUSINESS_PERFORMANCE_METRICS_ENABLED", False))


def _performance_metrics_path() -> Path:
    return Path(
        getattr(
            settings,
            "LOCAL_BUSINESS_PERFORMANCE_METRICS_PATH",
            settings.DATA_DIR / "logs" / "performance_events.jsonl",
        )
    )


def _performance_sample_rate() -> float:
    return float(getattr(settings, "LOCAL_BUSINESS_PERFORMANCE_METRICS_SAMPLE_RATE", 1.0))


def _should_sample() -> bool:
    sample_rate = _performance_sample_rate()
    if sample_rate >= 1:
        return True
    if sample_rate <= 0:
        return False
    return random.random() <= sample_rate


def _excluded_prefixes() -> tuple[str, ...]:
    return tuple(getattr(settings, "LOCAL_BUSINESS_PERFORMANCE_METRICS_EXCLUDE_PREFIXES", ("/static/", "/media/", "/favicon.")))


def _is_excluded_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _excluded_prefixes())


def _safe_route_metadata(request) -> tuple[str, str]:
    resolver_match = getattr(request, "resolver_match", None)
    if resolver_match is None:
        return "", ""
    route_name = resolver_match.view_name or resolver_match.url_name or ""
    route_pattern = getattr(resolver_match, "route", "") or ""
    return route_name, route_pattern


def _db_query_count_since(started_at: int) -> int | None:
    if not getattr(settings, "DEBUG", False):
        return None
    return max(0, len(connection.queries) - started_at)


def _normalise_event(event: dict[str, Any]) -> dict[str, Any]:
    safe_event = dict(event)
    safe_event.setdefault("schema_version", PERFORMANCE_EVENT_SCHEMA_VERSION)
    safe_event.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    safe_event.setdefault("event_type", HTTP_REQUEST_EVENT_TYPE)
    if "duration_ms" in safe_event:
        safe_event["duration_ms"] = round(float(safe_event["duration_ms"]), 3)
    return safe_event


def _iter_events(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping invalid performance event line in %s", path)
                continue
            if isinstance(payload, dict):
                yield payload


def _duration_ms(event: dict[str, Any]) -> float | None:
    try:
        return float(event["duration_ms"])
    except (KeyError, TypeError, ValueError):
        return None


def _group_key(event: dict[str, Any], group_by: str) -> str:
    if group_by == "none":
        return "all"
    value = str(event.get(group_by) or "").strip()
    return value or "unknown"


def _nearest_rank_percentile(sorted_values: list[float], percentile: int) -> float:
    if not sorted_values:
        return 0.0
    rank = max(1, int((percentile / 100) * len(sorted_values) + 0.999999))
    rank = min(rank, len(sorted_values))
    return round(sorted_values[rank - 1], 3)
