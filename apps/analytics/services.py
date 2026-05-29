from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.core.source_adapters import OPERATION_DELETE, SourceObjectEnvelope
from apps.core.json_utils import load_json_file
from apps.memory.security import scan_for_secrets

from .models import (
    AnalyticsCase,
    AnalyticsContentObject,
    AnalyticsDiagnosticRun,
    AnalyticsDuplicateCandidate,
    AnalyticsEvidenceRef,
    AnalyticsExtractionPacket,
    AnalyticsExtractionRun,
    AnalyticsFact,
    AnalyticsMetricCandidate,
    AnalyticsMetricSnapshot,
    AnalyticsSampleManifest,
    AnalyticsSignal,
    AnalyticsSource,
)


EXTRACTION_PACKET_SCHEMA_VERSION = "extraction-packet-v1"
ANALYTICS_FACT_SCHEMA_VERSION = "analytics-fact-v1"
JSONL_DATASET_VERSION = "analytics-jsonl-mvp-v1"


@dataclass(frozen=True)
class SyncResult:
    source_code: str
    discovered: int
    created: int
    updated: int
    dry_run: bool


def sync_sources_from_contracts():
    payload = analytics_sources_contract()
    synced = []
    for item in payload:
        source, _created = AnalyticsSource.objects.update_or_create(
            code=item["code"],
            defaults={
                "title": item["title"],
                "source_kind": item["source_kind"],
                "owner": item["owner"],
                "status": AnalyticsSource.Status.ENABLED if item["enabled"] else AnalyticsSource.Status.DISABLED,
                "scope_tokens": item["scope_tokens"],
                "sensitivity": item["sensitivity"],
                "config": item.get("config", {}),
            },
        )
        synced.append(source)
    return synced


def upsert_analytics_projection_from_envelope(
    envelope: SourceObjectEnvelope,
    *,
    facts=None,
    dry_run: bool = False,
):
    """Create or refresh analytics normalized projection from a source envelope."""
    if envelope.operation == OPERATION_DELETE:
        return delete_analytics_projection_from_envelope(envelope, dry_run=dry_run)

    normalized_text = normalize_text(envelope.text)
    raw_payload = json.dumps(envelope.payload or {}, ensure_ascii=False, sort_keys=True, default=str)
    fact_candidates = list(facts if facts is not None else (envelope.analytics or {}).get("fact_candidates", []))
    if dry_run:
        return {
            "source_code": envelope.source_code,
            "source_object_id": envelope.object_id,
            "content_object_id": "",
            "facts": len(fact_candidates),
            "dry_run": True,
        }

    source = _ensure_analytics_source_from_envelope(envelope)
    content_object, _created = AnalyticsContentObject.objects.update_or_create(
        source=source,
        source_object_id=envelope.object_id,
        defaults={
            "source_uri": f"source-adapter://{envelope.source_code}/{envelope.object_type}/{envelope.object_id}",
            "content_kind": envelope.object_type,
            "title": envelope.title,
            "raw_sha256": sha256_text(raw_payload),
            "normalized_text_sha256": sha256_text(normalized_text),
            "near_duplicate_key": near_duplicate_key(normalized_text),
            "business_key": str((envelope.payload or {}).get("business_key") or envelope.object_id),
            "scope_tokens": _envelope_scope_tokens(envelope),
            "sensitivity": envelope.sensitivity,
            "metadata": {
                "source_adapter": (envelope.provenance or {}).get("adapter", envelope.source_code),
                "schema_version": envelope.schema_version,
                "source_origin": envelope.source_origin,
                "source_kind": envelope.source_kind,
                "domain": envelope.domain,
                "object_type": envelope.object_type,
                "payload": dict(envelope.payload or {}),
                "relations": [dict(item) for item in envelope.relations],
                "privacy_profile": envelope.privacy_profile,
                "access_policy": dict(envelope.access_policy or {}),
                "safe_text": normalized_text,
                "content_hash": envelope.content_hash,
                "provenance": dict(envelope.provenance or {}),
            },
            "source_updated_at": envelope.source_updated_at,
            "is_active": True,
        },
    )
    evidence = ensure_source_adapter_evidence(content_object, envelope)
    packet = build_source_envelope_extraction_packet(content_object, envelope, fact_candidates, evidence_id=evidence.evidence_id)
    packet_obj = persist_extraction_packet(source, content_object, packet)
    persist_analytics_facts(packet_obj, packet["business_facts"])
    return {
        "source_code": source.code,
        "source_object_id": envelope.object_id,
        "content_object_id": content_object.id,
        "facts": len(packet["business_facts"]),
        "dry_run": False,
    }


def delete_analytics_projection_from_envelope(envelope: SourceObjectEnvelope, *, dry_run: bool = False):
    source = AnalyticsSource.objects.filter(code=envelope.source_code).first()
    if source is None:
        return {"source_code": envelope.source_code, "deactivated": 0, "dry_run": dry_run}
    content_object = AnalyticsContentObject.objects.filter(source=source, source_object_id=envelope.object_id).first()
    if content_object is None:
        return {"source_code": source.code, "deactivated": 0, "dry_run": dry_run}
    if dry_run:
        return {"source_code": source.code, "deactivated": 1, "dry_run": True}
    content_object.is_active = False
    content_object.save(update_fields=["is_active", "updated_at"])
    AnalyticsFact.objects.filter(source_packet__content_object=content_object).update(is_active=False)
    return {"source_code": source.code, "deactivated": 1, "dry_run": False}


def sync_analytics_source(*, source_code: str, dry_run: bool = False) -> SyncResult:
    source = get_contract_source(source_code)
    if source["source_kind"] != "email_imap":
        return SyncResult(source_code=source_code, discovered=0, created=0, updated=0, dry_run=dry_run)

    messages = source.get("config", {}).get("fixture_messages", [])
    created = 0
    updated = 0
    if dry_run:
        return SyncResult(source_code=source_code, discovered=len(messages), created=0, updated=0, dry_run=True)

    source_obj = _upsert_source_from_contract(source)
    for message in messages:
        content_object, was_created = upsert_email_content_object(source_obj, message)
        if was_created:
            created += 1
        else:
            updated += 1
        ensure_email_evidence(content_object, message)
    source_obj.last_synced_at = timezone.now()
    source_obj.watermarks = {
        **(source_obj.watermarks or {}),
        "last_fixture_uid": messages[-1].get("uid") if messages else None,
        "synced_at": timezone.now().isoformat(),
    }
    source_obj.save(update_fields=["last_synced_at", "watermarks", "updated_at"])
    return SyncResult(source_code=source_code, discovered=len(messages), created=created, updated=updated, dry_run=False)


def extract_analytics_source(*, source_code: str, dry_run: bool = False):
    source_obj = _ensure_source_model(source_code)
    run = AnalyticsExtractionRun.objects.create(
        source=source_obj,
        status=AnalyticsExtractionRun.Status.RUNNING,
        dry_run=dry_run,
        started_at=timezone.now(),
    )
    packets = []
    facts = []
    try:
        for content_object in source_obj.content_objects.filter(is_active=True).order_by("id"):
            packet = build_extraction_packet(content_object)
            packets.append(packet)
            facts.extend(packet["business_facts"])
            if not dry_run:
                packet_obj = persist_extraction_packet(source_obj, content_object, packet)
                persist_analytics_facts(packet_obj, packet["business_facts"])
        run.status = AnalyticsExtractionRun.Status.SUCCEEDED
        run.metrics = {"packets": len(packets), "facts": len(facts)}
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "metrics", "finished_at", "updated_at"])
    except Exception as exc:
        run.status = AnalyticsExtractionRun.Status.FAILED
        run.error_message = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        raise
    return {"run_id": run.id, "packets": len(packets), "facts": len(facts), "dry_run": dry_run}


def dedup_analytics_source(*, source_code: str, dry_run: bool = False):
    source_obj = _ensure_source_model(source_code)
    created = 0
    candidates = []
    objects = list(source_obj.content_objects.filter(is_active=True).order_by("id"))
    for index, item in enumerate(objects):
        for other in objects[index + 1:]:
            match_kind, score = classify_duplicate(item, other)
            if not match_kind:
                continue
            candidates.append((item, other, match_kind, score))
            if dry_run:
                continue
            _, was_created = AnalyticsDuplicateCandidate.objects.get_or_create(
                canonical_object=choose_canonical_content_object(item, other),
                duplicate_object=choose_duplicate_content_object(item, other),
                match_kind=match_kind,
                defaults={
                    "score": Decimal(str(score)),
                    "rationale": f"{match_kind} match from analytics dedup service",
                    "metadata": {
                        "source_code": source_code,
                        "left": item.source_object_id,
                        "right": other.source_object_id,
                    },
                },
            )
            if was_created:
                created += 1
    return {"source_code": source_code, "candidates": len(candidates), "created": created, "dry_run": dry_run}


def recalculate_metrics(*, dry_run: bool = False):
    metric_contracts = analytics_metrics_contract()
    monitor_contracts = analytics_monitors_contract()
    snapshots = []
    signals = []
    now = timezone.now()
    for metric in metric_contracts:
        facts = AnalyticsFact.objects.filter(fact_type=metric["fact_type"], is_active=True)
        value = aggregate_metric_value(metric, facts)
        snapshot_payload = {
            "metric_code": metric["code"],
            "window_start": None,
            "window_end": now,
            "value": value,
            "dimensions": {"aggregation": metric["aggregation"], "fact_type": metric["fact_type"]},
            "source_fact_count": facts.count(),
            "scope_tokens": metric.get("scope_tokens", []),
            "sensitivity": metric.get("sensitivity", "internal"),
        }
        snapshots.append(snapshot_payload)
        if not dry_run:
            dataset_path = append_jsonl_dataset("metrics/snapshots", snapshot_payload)
            snapshot = AnalyticsMetricSnapshot.objects.create(
                **snapshot_payload,
                dataset_path=str(dataset_path),
            )
            for monitor in monitor_contracts:
                if monitor["metric_code"] != metric["code"] or not monitor["enabled"]:
                    continue
                if monitor_condition_matches(value, monitor["condition"], Decimal(str(monitor["threshold"]))):
                    signals.append(create_signal_from_monitor(monitor, snapshot))
    return {"snapshots": len(snapshots), "signals": len(signals), "dry_run": dry_run}


def reflect_knowledge(*, dry_run: bool = False):
    grouped = {}
    for fact_type in AnalyticsFact.objects.filter(is_active=True).values_list("fact_type", flat=True):
        grouped[fact_type] = grouped.get(fact_type, 0) + 1
    candidates = []
    for fact_type, count in grouped.items():
        if count < 1:
            continue
        candidate_id = stable_id("metric-candidate", fact_type)
        payload = {
            "candidate_id": candidate_id,
            "title": f"Track repeated {fact_type}",
            "rationale": f"Fact type '{fact_type}' appeared {count} times and may deserve a dedicated metric.",
            "proposed_contract": {
                "code": f"{fact_type}_count",
                "fact_type": fact_type,
                "aggregation": "count",
                "window": "24h",
            },
            "evidence": [{"fact_type": fact_type, "count": count}],
        }
        candidates.append(payload)
        if not dry_run:
            AnalyticsMetricCandidate.objects.update_or_create(
                candidate_id=candidate_id,
                defaults={
                    "title": payload["title"],
                    "rationale": payload["rationale"],
                    "proposed_contract": payload["proposed_contract"],
                    "evidence": payload["evidence"],
                },
            )
    return {"candidates": len(candidates), "dry_run": dry_run}


def run_signal_diagnostic(*, signal_id: str, dry_run: bool = False):
    signal = AnalyticsSignal.objects.get(signal_id=signal_id)
    evidence_packet = build_evidence_packet(signal)
    result = {
        "summary": f"Signal {signal.signal_id} requires review through monitor {signal.monitor_code}.",
        "recommended_route": route_for_signal(signal),
        "recommended_actions": ["create_draft_case"],
        "confidence": 0.75,
    }
    if dry_run:
        return {
            "diagnostic_run_id": "",
            "signal_id": signal.signal_id,
            "case_id": "",
            "route": result["recommended_route"],
            "dry_run": True,
            "evidence_packet": evidence_packet,
        }

    run = AnalyticsDiagnosticRun.objects.create(
        signal=signal,
        status=AnalyticsDiagnosticRun.Status.SUCCEEDED,
        dry_run=False,
        evidence_packet=evidence_packet,
        result=result,
        started_at=timezone.now(),
        finished_at=timezone.now(),
    )
    signal.status = AnalyticsSignal.Status.ROUTED
    signal.save(update_fields=["status", "updated_at"])
    case = AnalyticsCase.objects.create(
        case_id=stable_id("analytics-case", signal.signal_id, str(run.id)),
        signal=signal,
        route_code=result["recommended_route"],
        payload={"diagnostic_run_id": run.id, "result": result},
    )
    return {
        "diagnostic_run_id": run.id,
        "signal_id": signal.signal_id,
        "case_id": case.case_id if case else "",
        "route": result["recommended_route"],
        "dry_run": False,
    }


def upsert_email_content_object(source: AnalyticsSource, message: dict):
    body = normalize_text("\n".join(part for part in (message.get("subject", ""), message.get("body", "")) if part))
    raw_payload = json.dumps(message, ensure_ascii=False, sort_keys=True)
    source_object_id = email_source_object_id(source, message)
    metadata = {
        "message_id": message.get("message_id", ""),
        "folder": message.get("folder", ""),
        "uidvalidity": message.get("uidvalidity", ""),
        "uid": message.get("uid", ""),
        "from": message.get("from", ""),
        "to": message.get("to", []),
        "sent_at": message.get("sent_at", ""),
        "subject": message.get("subject", ""),
        "body": body,
        "attachments": message.get("attachments", []),
    }
    content_object, created = AnalyticsContentObject.objects.update_or_create(
        source=source,
        source_object_id=source_object_id,
        defaults={
            "source_uri": f"imap://{source.config.get('mailbox_code', source.code)}/{message.get('folder', '')}/{message.get('uid', '')}",
            "content_kind": "email_message",
            "title": message.get("subject", ""),
            "raw_sha256": sha256_text(raw_payload),
            "normalized_text_sha256": sha256_text(body),
            "near_duplicate_key": near_duplicate_key(body),
            "business_key": business_key_for_message(message, body),
            "scope_tokens": source.scope_tokens,
            "sensitivity": source.sensitivity,
            "metadata": metadata,
            "source_updated_at": parse_datetime(message.get("sent_at", "")),
            "is_active": True,
        },
    )
    return content_object, created


def ensure_email_evidence(content_object: AnalyticsContentObject, message: dict):
    evidence_id = stable_id("email-evidence", content_object.source.code, content_object.source_object_id)
    AnalyticsEvidenceRef.objects.get_or_create(
        evidence_id=evidence_id,
        defaults={
            "content_object": content_object,
            "ref_kind": "email_imap",
            "ref_value": content_object.source_uri,
            "authority_rank": 40,
            "metadata": {
                "message_id": message.get("message_id", ""),
                "folder": message.get("folder", ""),
                "uid": message.get("uid", ""),
            },
        },
    )


def ensure_source_adapter_evidence(content_object: AnalyticsContentObject, envelope: SourceObjectEnvelope):
    evidence_id = stable_id("source-adapter-evidence", envelope.source_code, envelope.object_id)
    evidence, _created = AnalyticsEvidenceRef.objects.update_or_create(
        evidence_id=evidence_id,
        defaults={
            "content_object": content_object,
            "ref_kind": "source_adapter",
            "ref_value": f"{envelope.source_code}:{envelope.object_type}:{envelope.object_id}",
            "authority_rank": 20,
            "metadata": {
                "source_code": envelope.source_code,
                "source_kind": envelope.source_kind,
                "domain": envelope.domain,
                "content_hash": envelope.content_hash,
            },
        },
    )
    return evidence


def build_source_envelope_extraction_packet(content_object: AnalyticsContentObject, envelope: SourceObjectEnvelope, facts, *, evidence_id: str):
    text = normalize_text(envelope.text)
    secret_scan = scan_for_secrets(text)
    if secret_scan.blocked:
        raise ValidationError("Проекция аналитики заблокирована: пакет источника содержит учетные данные или секрет.")
    normalized_facts = [
        normalize_source_envelope_fact(content_object=content_object, envelope=envelope, fact=fact, evidence_id=evidence_id)
        for fact in facts
    ]
    return {
        "schema_version": EXTRACTION_PACKET_SCHEMA_VERSION,
        "source_identity": {
            "source_code": envelope.source_code,
            "source_kind": envelope.source_kind,
            "external_id": envelope.object_id,
        },
        "fingerprints": {
            "raw_sha256": content_object.raw_sha256,
            "normalized_text_sha256": content_object.normalized_text_sha256,
            "near_duplicate_key": content_object.near_duplicate_key,
            "semantic_claim_hashes": [fact["semantic_hash"] for fact in normalized_facts],
        },
        "safe_text": text,
        "entities": extract_simple_entities(text),
        "claims": [],
        "business_facts": normalized_facts,
        "scope_tokens": content_object.scope_tokens,
        "sensitivity": content_object.sensitivity,
        "provenance": {
            "extractor": "source-envelope-adapter-v1",
            "content_object_id": content_object.id,
            "envelope_id": envelope.envelope_id,
        },
    }


def normalize_source_envelope_fact(*, content_object: AnalyticsContentObject, envelope: SourceObjectEnvelope, fact: dict, evidence_id: str):
    fact_type = str(fact.get("fact_type") or "").strip()
    if not fact_type:
        raise ValidationError("Факт аналитики из адаптера источника должен содержать fact_type.")
    dimensions = dict(fact.get("dimensions") or {})
    measures = dict(fact.get("measures") or {})
    semantic_hash = fact.get("semantic_hash") or sha256_text(
        json.dumps(
            {
                "source_code": envelope.source_code,
                "object_id": envelope.object_id,
                "fact_type": fact_type,
                "dimensions": dimensions,
                "measures": measures,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
    )
    return {
        "schema_version": ANALYTICS_FACT_SCHEMA_VERSION,
        "fact_id": fact.get("fact_id") or stable_id("analytics-fact", envelope.source_code, envelope.object_id, fact_type, semantic_hash),
        "fact_type": fact_type,
        "event_time": fact.get("event_time") or (envelope.source_updated_at.isoformat() if envelope.source_updated_at else timezone.now().isoformat()),
        "dimensions": dimensions,
        "measures": measures,
        "evidence_refs": fact.get("evidence_refs") or [evidence_id],
        "semantic_hash": semantic_hash,
        "scope_tokens": fact.get("scope_tokens") or content_object.scope_tokens,
        "sensitivity": fact.get("sensitivity") or content_object.sensitivity,
    }


def build_extraction_packet(content_object: AnalyticsContentObject):
    text = content_object.metadata.get("body", "")
    secret_scan = scan_for_secrets(text)
    if secret_scan.blocked:
        raise ValidationError("Извлечение аналитики заблокировано: содержимое источника содержит учетные данные или секрет.")
    facts = extract_business_facts(content_object, text)
    packet = {
        "schema_version": EXTRACTION_PACKET_SCHEMA_VERSION,
        "source_identity": {
            "source_code": content_object.source.code,
            "source_kind": content_object.source.source_kind,
            "external_id": content_object.source_object_id,
        },
        "fingerprints": {
            "raw_sha256": content_object.raw_sha256,
            "normalized_text_sha256": content_object.normalized_text_sha256,
            "near_duplicate_key": content_object.near_duplicate_key,
            "semantic_claim_hashes": [fact["semantic_hash"] for fact in facts],
        },
        "safe_text": text,
        "entities": extract_simple_entities(text),
        "claims": [],
        "business_facts": facts,
        "scope_tokens": content_object.scope_tokens,
        "sensitivity": content_object.sensitivity,
        "provenance": {
            "extractor": "analytics-local-pattern-extractor-v1",
            "content_object_id": content_object.id,
        },
    }
    return packet


def persist_extraction_packet(source, content_object, packet):
    packet_id = stable_id("extraction-packet", source.code, content_object.source_object_id, content_object.normalized_text_sha256)
    packet_obj, _created = AnalyticsExtractionPacket.objects.update_or_create(
        packet_id=packet_id,
        defaults={
            "source": source,
            "content_object": content_object,
            "packet": packet,
            "scope_tokens": packet.get("scope_tokens", []),
            "sensitivity": packet.get("sensitivity", "internal"),
        },
    )
    append_jsonl_dataset("normalized/extraction_packets", {"packet_id": packet_id, "packet": packet})
    return packet_obj


def persist_analytics_facts(packet_obj, facts):
    for fact in facts:
        AnalyticsFact.objects.update_or_create(
            fact_id=fact["fact_id"],
            defaults={
                "fact_type": fact["fact_type"],
                "event_time": parse_datetime(fact["event_time"]) if fact.get("event_time") else None,
                "dimensions": fact.get("dimensions", {}),
                "measures": fact.get("measures", {}),
                "evidence_refs": fact.get("evidence_refs", []),
                "semantic_hash": fact["semantic_hash"],
                "scope_tokens": fact.get("scope_tokens", []),
                "sensitivity": fact.get("sensitivity", "internal"),
                "source_packet": packet_obj,
                "is_active": True,
            },
        )
        append_jsonl_dataset("normalized/business_facts", fact)


def extract_business_facts(content_object, text):
    facts = []
    lower = text.lower()
    event_time = content_object.metadata.get("sent_at") or timezone.now().isoformat()
    evidence_refs = list(content_object.evidence_refs.values_list("evidence_id", flat=True))
    if "отчет завед" in lower or "отчет заведующего" in lower:
        department = extract_department(text) or "unknown"
        period = extract_period(text) or ""
        facts.append(build_fact(
            content_object=content_object,
            fact_type="department_report_received",
            event_time=event_time,
            dimensions={"department": department, "period": period, "author": content_object.metadata.get("from", "")},
            measures={"reports": 1},
            evidence_refs=evidence_refs,
        ))
    if any(marker in lower for marker in ("риск", "проблем", "дефицит", "сбой", "просроч")):
        facts.append(build_fact(
            content_object=content_object,
            fact_type="department_issue_reported",
            event_time=event_time,
            dimensions={"department": extract_department(text) or "unknown", "issue_type": extract_issue_type(text), "period": extract_period(text) or ""},
            measures={"issues": 1},
            evidence_refs=evidence_refs,
        ))
    if any(marker in lower for marker in ("росздравнадзор", "регулятор", "запрос")):
        facts.append(build_fact(
            content_object=content_object,
            fact_type="regulator_request_received",
            event_time=event_time,
            dimensions={"regulator": extract_regulator(text), "topic": extract_topic(text), "department": extract_department(text) or "unknown"},
            measures={"requests": 1, "requested_documents": extract_first_int(text) or 0, "deadline_days": extract_deadline_days(text) or 0},
            evidence_refs=evidence_refs,
        ))
    if any(marker in lower for marker in ("до 20", "срок", "дедлайн", "обязательство")):
        facts.append(build_fact(
            content_object=content_object,
            fact_type="deadline_committed",
            event_time=event_time,
            dimensions={"department": extract_department(text) or "unknown", "commitment_type": "deadline"},
            measures={"commitments": 1},
            evidence_refs=evidence_refs,
        ))
    return facts


def build_fact(*, content_object, fact_type, event_time, dimensions, measures, evidence_refs):
    semantic_hash = sha256_text(json.dumps({
        "fact_type": fact_type,
        "dimensions": dimensions,
        "measures": measures,
    }, ensure_ascii=False, sort_keys=True))
    return {
        "schema_version": ANALYTICS_FACT_SCHEMA_VERSION,
        "fact_id": stable_id("analytics-fact", fact_type, semantic_hash),
        "fact_type": fact_type,
        "event_time": event_time,
        "dimensions": dimensions,
        "measures": measures,
        "evidence_refs": evidence_refs,
        "semantic_hash": semantic_hash,
        "scope_tokens": content_object.scope_tokens,
        "sensitivity": content_object.sensitivity,
    }


def classify_duplicate(left, right):
    if left.raw_sha256 and left.raw_sha256 == right.raw_sha256:
        return "exact_raw_hash", 1
    if left.normalized_text_sha256 and left.normalized_text_sha256 == right.normalized_text_sha256:
        return "exact_normalized_text_hash", 1
    if left.business_key and left.business_key == right.business_key:
        return "business_key", 0.9
    if left.near_duplicate_key and left.near_duplicate_key == right.near_duplicate_key:
        return "near_duplicate", 0.75
    return "", 0


def choose_canonical_content_object(left, right):
    return left if authority_rank(left) <= authority_rank(right) else right


def choose_duplicate_content_object(left, right):
    return right if choose_canonical_content_object(left, right).pk == left.pk else left


def authority_rank(content_object):
    kind = content_object.metadata.get("authority_kind") or content_object.content_kind
    return {
        "dms_registered": 10,
        "dms_approved": 20,
        "email_attachment": 30,
        "email_message": 40,
        "file_share": 50,
        "chat_paste": 60,
    }.get(kind, 100)


def aggregate_metric_value(metric, facts):
    aggregation = metric["aggregation"]
    measure = metric.get("measure", "")
    if aggregation == "count":
        return Decimal(facts.count())
    values = [Decimal(str((fact.measures or {}).get(measure, 0) or 0)) for fact in facts]
    if not values:
        return Decimal("0")
    if aggregation == "sum":
        return sum(values, Decimal("0"))
    if aggregation == "avg":
        return sum(values, Decimal("0")) / Decimal(len(values))
    if aggregation == "min":
        return min(values)
    if aggregation == "max":
        return max(values)
    raise ValidationError(f"Unsupported aggregation: {aggregation}")


def monitor_condition_matches(value, condition, threshold):
    value = Decimal(str(value))
    if condition == "gt":
        return value > threshold
    if condition == "gte":
        return value >= threshold
    if condition == "lt":
        return value < threshold
    if condition == "lte":
        return value <= threshold
    if condition == "eq":
        return value == threshold
    if condition == "neq":
        return value != threshold
    raise ValidationError(f"Unsupported monitor condition: {condition}")


def create_signal_from_monitor(monitor, snapshot):
    signal_id = stable_id("analytics-signal", monitor["code"], str(snapshot.id))
    signal, _created = AnalyticsSignal.objects.get_or_create(
        signal_id=signal_id,
        defaults={
            "monitor_code": monitor["code"],
            "metric_snapshot": snapshot,
            "severity": monitor["severity"],
            "message": f"Monitor {monitor['code']} matched value {snapshot.value}.",
            "evidence": [{"metric_snapshot_id": snapshot.id, "metric_code": snapshot.metric_code}],
            "scope_tokens": snapshot.scope_tokens,
            "sensitivity": snapshot.sensitivity,
        },
    )
    return signal


def build_evidence_packet(signal):
    snapshot = signal.metric_snapshot
    facts = []
    if snapshot:
        fact_type = (snapshot.dimensions or {}).get("fact_type")
        facts = list(
            AnalyticsFact.objects.filter(fact_type=fact_type, is_active=True)
            .order_by("-event_time", "-id")
            .values("fact_id", "fact_type", "dimensions", "measures", "evidence_refs")[:20]
        )
    return {
        "signal_id": signal.signal_id,
        "monitor_code": signal.monitor_code,
        "message": signal.message,
        "facts": facts,
        "scope_tokens": signal.scope_tokens,
        "sensitivity": signal.sensitivity,
    }


def route_for_signal(signal):
    for monitor in analytics_monitors_contract():
        if monitor["code"] == signal.monitor_code:
            return monitor["workflow_route"]
    return "analytics_review"


def append_jsonl_dataset(relative_dir, payload):
    path = Path(settings.DATA_DIR) / "analytics" / relative_dir / f"{timezone.now():%Y-%m-%d}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"dataset_version": JSONL_DATASET_VERSION, **payload}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return path


def build_sample_manifest(*, scope_rule_code, source_codes, selected_object_ids, sampling_strategy, limits):
    manifest_id = stable_id("sample-manifest", scope_rule_code, timezone.now().isoformat())
    manifest = AnalyticsSampleManifest.objects.create(
        manifest_id=manifest_id,
        scope_rule_code=scope_rule_code,
        source_codes=source_codes,
        selected_object_ids=selected_object_ids,
        sampling_strategy=sampling_strategy,
        limits=limits,
    )
    append_jsonl_dataset("lineage/sample_manifests", {
        "manifest_id": manifest.manifest_id,
        "scope_rule_code": scope_rule_code,
        "source_codes": source_codes,
        "selected_object_ids": selected_object_ids,
        "sampling_strategy": sampling_strategy,
        "limits": limits,
    })
    return manifest


def _ensure_source_model(source_code):
    try:
        return AnalyticsSource.objects.get(code=source_code)
    except AnalyticsSource.DoesNotExist:
        contract = get_contract_source(source_code)
        return _upsert_source_from_contract(contract)


def _ensure_analytics_source_from_envelope(envelope: SourceObjectEnvelope):
    config = {
        "source_origin": envelope.source_origin,
        "source_kind": envelope.source_kind,
        "domain": envelope.domain,
        "privacy_profile": envelope.privacy_profile,
        "access_policy": dict(envelope.access_policy or {}),
        "source_adapter": (envelope.provenance or {}).get("adapter", envelope.source_code),
        "schema_version": envelope.schema_version,
    }
    source, _created = AnalyticsSource.objects.update_or_create(
        code=envelope.source_code,
        defaults={
            "title": str((envelope.provenance or {}).get("source_title") or envelope.source_code).replace("_", " ").title(),
            "source_kind": envelope.source_kind,
            "owner": envelope.domain or "analytics",
            "status": AnalyticsSource.Status.ENABLED,
            "scope_tokens": _envelope_scope_tokens(envelope),
            "sensitivity": envelope.sensitivity,
            "config": config,
        },
    )
    return source


def _upsert_source_from_contract(contract):
    source, _created = AnalyticsSource.objects.update_or_create(
        code=contract["code"],
        defaults={
            "title": contract["title"],
            "source_kind": contract["source_kind"],
            "owner": contract["owner"],
            "status": AnalyticsSource.Status.ENABLED if contract["enabled"] else AnalyticsSource.Status.DISABLED,
            "scope_tokens": contract["scope_tokens"],
            "sensitivity": contract["sensitivity"],
            "config": contract.get("config", {}),
        },
    )
    return source


def _envelope_scope_tokens(envelope: SourceObjectEnvelope) -> list[str]:
    return sorted({str(token) for token in (envelope.access_policy or {}).get("scope_tokens", []) if str(token).strip()})


def get_contract_source(source_code):
    for source in analytics_sources_contract():
        if source["code"] == source_code:
            return source
    raise ValidationError(f"Источник аналитики '{source_code}' не объявлен.")


def analytics_sources_contract():
    return load_json_file(settings.LOCAL_BUSINESS_ANALYTICS_SOURCES_FILE)


def analytics_metrics_contract():
    return load_json_file(settings.LOCAL_BUSINESS_ANALYTICS_METRICS_FILE)


def analytics_monitors_contract():
    return load_json_file(settings.LOCAL_BUSINESS_ANALYTICS_MONITORS_FILE)


def email_source_object_id(source, message):
    return ":".join([
        str(source.config.get("mailbox_code", source.code)),
        str(message.get("folder", "")),
        str(message.get("uidvalidity", "")),
        str(message.get("uid", "")),
    ])


def business_key_for_message(message, body):
    subject = normalize_text(message.get("subject", "")).lower()
    period = extract_period(subject + " " + body) or ""
    department = extract_department(subject + " " + body) or ""
    request_number = extract_request_number(subject + " " + body) or ""
    if request_number:
        return f"regulator:{request_number}"
    if period and department:
        return f"department-report:{department}:{period}"
    return ""


def normalize_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def sha256_text(value):
    return "sha256:" + hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def stable_id(*parts):
    return ":".join(str(part).replace(" ", "_") for part in parts if part != "")


def near_duplicate_key(text):
    words = sorted(set(re.findall(r"[A-Za-zА-Яа-яЁё0-9]{4,}", (text or "").lower())))
    return sha256_text(" ".join(words[:80])) if words else ""


def extract_simple_entities(text):
    entities = []
    department = extract_department(text)
    if department:
        entities.append({"type": "department", "value": department})
    regulator = extract_regulator(text)
    if regulator != "unknown":
        entities.append({"type": "regulator", "value": regulator})
    return entities


def extract_department(text):
    match = re.search(r"отделени[ея]\s+([А-Яа-яЁёA-Za-z0-9_-]+)", text or "", flags=re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return ""


def extract_period(text):
    match = re.search(r"(20\d{2}-W\d{1,2}|20\d{2}-\d{2}-\d{2})", text or "")
    return match.group(1) if match else ""


def extract_issue_type(text):
    lower = (text or "").lower()
    if "дефицит" in lower or "кадров" in lower:
        return "staff_shortage"
    if "оборуд" in lower:
        return "equipment"
    if "просроч" in lower:
        return "overdue"
    return "general"


def extract_regulator(text):
    lower = (text or "").lower()
    if "росздравнадзор" in lower:
        return "roszdravnadzor"
    if "регулятор" in lower:
        return "regulator"
    return "unknown"


def extract_topic(text):
    lower = (text or "").lower()
    if "узи" in lower:
        return "ultrasound_reports"
    if "мрт" in lower:
        return "mri"
    return "general"


def extract_first_int(text):
    match = re.search(r"\b(\d{1,4})\b", text or "")
    return int(match.group(1)) if match else 0


def extract_deadline_days(text):
    match = re.search(r"срок[^\d]{0,20}(\d{1,3})\s*(дн|день|дня|дней)", text or "", flags=re.IGNORECASE)
    return int(match.group(1)) if match else 0


def extract_request_number(text):
    match = re.search(r"(?:N|№)\s*([A-Za-zА-Яа-яЁё0-9_-]+)", text or "", flags=re.IGNORECASE)
    return match.group(1) if match else ""
