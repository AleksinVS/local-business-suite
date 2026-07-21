"""Общий preamble для разбитого набора тестов memory (импорты, фикстуры, mixin).

Не является тест-модулем (имя не совпадает с шаблоном discovery). Тематические
модули берут отсюда имена через ``from ..tests._common import *``.
"""
import json
import os
from datetime import timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command, get_commands
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.analytics.models import AnalyticsContentObject, AnalyticsFact
from apps.core.models import Department
from apps.inventory.models import MedicalDevice
from apps.waiting_list.models import WaitingListEntry
from apps.workorders.models import Board, WorkOrder, WorkOrderStatus
from apps.workorders.policies import ROLE_CUSTOMER, ROLE_MANAGER, ROLE_TECHNICIAN

from ..admin import (
    MemoryAccessAuditAdmin,
    MemoryEvalCaseAdmin,
    MemoryKnowledgeItemAdmin,
    MemorySearchDocumentAdmin,
    MemorySourceAdmin,
)
from ..models import (
    MemoryAccessAudit,
    MemoryEvalCase,
    MemoryExternalConnectorJob,
    MemoryIngestionIssue,
    MemoryIngestionRun,
    MemoryKnowledgeEdge,
    MemoryKnowledgeItem,
    MemorySearchDocument,
    MemorySource,
    MemorySourceObject,
    SecretAccessAudit,
    SecretHandle,
)
from ..policies import can_access_search_document, can_manage_memory, effective_source_trust, user_scope_tokens
from ..review_selectors import index_document_queryset, issue_to_review_queue_item, pending_knowledge_queryset, review_issue_queryset
from ..review_services import apply_index_review_action, apply_issue_review_action
from ..knowledge_files import read_knowledge_item_file
from ..services import (
    MemoryQueueJobKind,
    complete_memory_queue_task,
    enqueue_memory_queue_task,
    fail_memory_queue_task,
    lease_memory_queue_tasks,
    record_access_audit,
    sync_sources_from_contract,
)

User = get_user_model()
RUNTIME_DATABASES = {"default"}


def _memory_ingestion_profiles_with_acl(*, acl_mode, unresolved_policy):
    payload = json.loads(json.dumps(settings.LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES))
    profile_id = "corporate_docs_acl_test_v1"
    payload["profiles"][profile_id] = {
        **payload["profiles"]["corporate_docs_windows_v1"],
        "acl_mode": acl_mode,
        "acl_policy": {
            "unresolved_policy": unresolved_policy,
            "fail_closed": True,
            "group_nesting_depth": 5,
            "cache_ttl_seconds": 3600,
        },
    }
    return payload


MEMORY_INGESTION_BOOTSTRAP_MODELS = {
    "MemorySourceObject": {
        "source",
        "object_id",
        "object_uri",
        "relative_path",
        "file_name",
        "extension",
        "mime_type",
        "size_bytes",
        "mtime",
        "content_hash",
        "etag_or_inode",
        "last_seen_at",
        "last_stable_at",
        "discovery_status",
        "ingestion_status",
        "last_ingested_at",
        "failure_count",
        "last_error",
        "partial_reason",
        "acl_fingerprint",
        "metadata",
    },
    "MemoryIngestionRun": {
        "source",
        "status",
        "started_at",
        "finished_at",
        "dry_run",
        "metrics",
        "error_message",
    },
    "MemoryIngestionIssue": {
        "source",
        "source_object",
        "run",
        "issue_kind",
        "status",
        "severity",
        "message",
        "metadata",
    },
}


def get_optional_memory_model(model_name):
    try:
        return apps.get_model("memory", model_name)
    except LookupError:
        return None


class MemoryModelFactoryMixin:
    def create_source(self, code="workorders_public_timeline", **overrides):
        defaults = {
            "code": code,
            "title": "Work orders public timeline",
            "source_kind": "django_model",
            "domain": "workorders",
            "owner": "operations",
            "sensitivity": "internal",
            "pii_policy": "deidentify_before_index",
            "index_profiles": ["fulltext_default"],
        }
        defaults.update(overrides)
        return MemorySource.objects.create(**defaults)

    def create_search_document(self, source=None, document_id="doc-1", **overrides):
        source = source or self.create_source()
        scope_tokens = overrides.pop("scope_tokens", ["org:default"])
        sensitivity = overrides.pop("sensitivity", "internal")
        if source.sensitivity != sensitivity:
            source.sensitivity = sensitivity
            source.save(update_fields=["sensitivity", "updated_at"])
        source_object = overrides.pop("source_object", None) or MemorySourceObject.objects.create(
            source=source,
            object_id="object-1",
            object_uri="source://object-1",
            relative_path="object-1.txt",
            file_name="object-1.txt",
            mime_type="text/plain",
            content_hash="text-hash-1",
            metadata={"scope_tokens": scope_tokens},
        )
        defaults = {
            "document_id": document_id,
            "corpus_type": MemorySearchDocument.CorpusType.SOURCE_DATA,
            "object_kind": MemorySearchDocument.ObjectKind.SOURCE_OBJECT,
            "source_object": source_object,
            "body_hash": "text-hash-1",
            "index_status": MemorySearchDocument.IndexStatus.READY,
            "metadata": {"section": "timeline"},
        }
        defaults.update(overrides)
        return MemorySearchDocument.objects.create(**defaults)
