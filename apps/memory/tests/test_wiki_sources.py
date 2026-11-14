import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings

from apps.core.models import Department
from apps.core.source_adapters import get_source_adapter
from apps.memory.models import MemorySearchDocument, MemorySource, MemorySourceObject
from apps.memory.services import sha256_text, upsert_memory_projection_from_envelope
from apps.memory.wiki_config import WikiBundle
from apps.memory.wiki_sources import wiki_source_preview, wiki_sources_allowed
from apps.workorders.models import Board, WorkOrder
from apps.workorders.policies import ROLE_MANAGER

pytestmark = pytest.mark.integration


@override_settings(LOCAL_BUSINESS_MEMORY_TEST_SOURCE_ALLOWLIST=["wiki_fixture"])
class WikiSourceTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username="wiki-author")
        self.reader = get_user_model().objects.create_user(username="wiki-reader")
        self.bundle = WikiBundle("manual", "org/crow/manual", ("org:default",), model_context=True)
        self.text = "Issued materials are returned to the warehouse after the work order closes."
        self.source = MemorySource.objects.create(
            code="wiki_fixture", title="Manual", source_kind="synthetic_fixture", domain="ops",
            sensitivity="internal", trust_status="trusted", trusted_for_context=True,
        )
        self.obj = MemorySourceObject.objects.create(
            source=self.source, object_id="warehouse-rule", content_hash="source-version",
            ingestion_status="ingested", metadata={"safe_text": self.text, "scope_tokens": ["org:default"]},
        )
        digest = sha256_text(self.text)
        self.doc = MemorySearchDocument.objects.create(
            document_id="fixture-source-page", corpus_type="source_data", object_kind="source_object",
            source_object=self.obj, index_status="ready", body_hash=digest,
            metadata={"content_hash": "source-version", "sensitivity": "internal", "safe_text_hash": digest},
        )

    def preview(self, bundle=None):
        return wiki_source_preview(self.actor, bundle or self.bundle, self.source.code, self.obj.object_id)

    def test_preview_and_refs_recheck_text_hash_source_status_and_ingest_state(self):
        result = self.preview()
        ref = result["source_ref"]
        self.assertEqual(result["text"], self.text)
        self.assertEqual(ref, {
            "source_code": self.source.code, "source_object_id": self.obj.object_id, "text_hash": sha256_text(self.text),
        })
        self.assertTrue(wiki_sources_allowed(self.actor, self.bundle, [ref]))
        self.assertFalse(wiki_sources_allowed(self.actor, self.bundle, [dict(ref, text_hash="0" * 64)]))
        self.assertFalse(wiki_sources_allowed(self.actor, self.bundle, [dict(ref, url="file:///etc")]))
        for instance, field, new, old in [
            (self.source, "status", "disabled", "enabled"),
            (self.source, "trust_status", "blocked", "trusted"),
            (self.obj, "discovery_status", "missing", "seen"),
            (self.doc, "index_status", "deleted", "ready"),
            (self.obj, "content_hash", "new-version", "source-version"),
        ]:
            with self.subTest(field=field):
                setattr(instance, field, new)
                instance.save()
                self.assertFalse(wiki_sources_allowed(self.actor, self.bundle, [ref]))
                setattr(instance, field, old)
                instance.save()
        self.obj.metadata["safe_text"] = "Unindexed change"
        self.obj.save()
        with self.assertRaises(PermissionDenied):
            self.preview()

    def test_filename_original_pii_secrets_and_lower_sensitivity_are_rejected(self):
        for unsafe in ("", "Address: employee@example.org", "API_KEY=0123456789abcdef"):
            with self.subTest(text=unsafe):
                self.obj.metadata["safe_text"] = unsafe
                self.obj.file_name = "must never be used"
                self.obj.save()
                self.doc.body_hash = sha256_text(unsafe)
                self.doc.metadata["safe_text_hash"] = self.doc.body_hash
                self.doc.save()
                with self.assertRaises(PermissionDenied):
                    self.preview()
        with self.assertRaises(PermissionDenied):
            self.preview(replace(self.bundle, sensitivity="public"))

    def test_normal_workorder_projection_is_available_until_the_upstream_record_changes(self):
        group, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
        self.actor.groups.add(group)
        board = Board.objects.create(title="Workshop", slug="wiki-workshop")
        board.allowed_groups.add(group)
        order = WorkOrder.objects.create(
            title="Inspect packing equipment", description="Replace the inlet gasket.",
            department=Department.objects.create(name="Workshop"), author=self.actor, board=board,
        )
        adapter = get_source_adapter("workorders")
        envelope = adapter.render_envelope(adapter.get_object(str(order.pk)))
        with TemporaryDirectory() as directory, override_settings(
            DATA_DIR=Path(directory), RUNTIME_CONTRACTS_DIR=Path(directory) / "contracts",
            LOCAL_BUSINESS_MEMORY_VECTOR_BACKEND="disabled",
        ):
            upsert_memory_projection_from_envelope(envelope, index_backends=())
            bundle = replace(self.bundle, read_tokens=(f"user:{self.actor.pk}",))
            result = wiki_source_preview(self.actor, bundle, "workorders", str(order.pk))
            self.assertIn("Replace the inlet gasket.", result["text"])
            self.assertTrue(wiki_sources_allowed(self.actor, bundle, [result["source_ref"]]))
            order.description = "Иван\nПетров"
            order.save()
            self.assertFalse(wiki_sources_allowed(self.actor, bundle, [result["source_ref"]]))
            envelope = adapter.render_envelope(adapter.get_object(str(order.pk)))
            upsert_memory_projection_from_envelope(envelope, index_backends=())
            with self.assertRaises(PermissionDenied):
                wiki_source_preview(self.actor, bundle, "workorders", str(order.pk))

    def test_dynamic_acl_requires_all_named_users_and_current_source_version(self):
        audience = (f"user:{self.actor.pk}", f"user:{self.reader.pk}")
        bundle = replace(self.bundle, read_tokens=audience)
        policy = {"mode": "adapter_check", "scope_tokens": ["org:default"]}
        self.obj.metadata.update(access_policy=policy, source_adapter="fixture", privacy_profile="pii_guarded")
        self.obj.save()
        envelope = SimpleNamespace(
            operation="upsert", source_code=self.source.code, object_id=self.obj.object_id,
            content_hash=self.obj.content_hash, access_policy=policy, sensitivity="internal", privacy_profile="pii_guarded",
        )
        allowed = {self.actor.pk, self.reader.pk}
        adapter = SimpleNamespace(
            can_access=lambda user, key: key == self.obj.object_id and user.pk in allowed,
            get_object=lambda key: self.obj, render_envelope=lambda record: envelope,
        )
        with patch("apps.memory.services.get_source_adapter", return_value=adapter), patch(
            "apps.memory.wiki_sources.get_source_adapter", return_value=adapter
        ):
            ref = self.preview(bundle)["source_ref"]
            with self.assertRaises(PermissionDenied):
                self.preview()
            allowed.remove(self.reader.pk)
            self.assertFalse(wiki_sources_allowed(self.actor, bundle, [ref]))
            allowed.add(self.reader.pk)
            envelope.content_hash = "changed before the projection updated"
            self.assertFalse(wiki_sources_allowed(self.actor, bundle, [ref]))

    def test_memory_gateway_and_direct_read_use_the_same_revision_and_current_acl(self):
        from apps.ai.models import AgentActionLog, ChatMessage
        from apps.ai.tooling import execute_tool
        from apps.memory.knowledge_files import read_knowledge_for_actor
        from apps.memory.models import MemoryAccessAudit, MemoryKnowledgeItem
        from apps.memory.wiki_config import wiki_bundles
        from apps.memory.wiki_reconcile import reconcile_wiki_bundle

        root = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, {"LOCAL_BUSINESS_KNOWLEDGE_REPO_DIR": str(root)}))
        registry = {"manual": {"path": "org/crow/manual", "projection_user_id": self.actor.pk,
                               "read_tokens": ["org:default"], "model_context": True,
                               "note_read_tokens": {"private-rule": [f"user:{self.actor.pk}"]}}}
        self.enterContext(override_settings(LOCAL_BUSINESS_WIKI_BUNDLES=registry, LOCAL_BUSINESS_WIKI_SEARCH="basic"))
        directory = root / self.bundle.path
        directory.mkdir(parents=True)
        ref = self.preview()["source_ref"]
        for key, body in {"visible-rule": "A dispatch requires a packing slip.",
                          "private-rule": "A dispatch requires a restricted invoice."}.items():
            metadata = {"type": "Note", "knowledge_id": key, "title": "Dispatch", "description": "Warehouse",
                        "source_refs": [ref]}
            (directory / f"{key}.md").write_text("---\n" + yaml.safe_dump(metadata) + "---\n\n" + body)
        for args in [("init",), ("add", "."), ("-c", "user.name=Fixture", "-c", "user.email=wiki@local",
                                          "commit", "-m", "Rules")]:
            subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)
        ready = reconcile_wiki_bundle(wiki_bundles()["manual"])
        self.assertEqual(ready["status"], "ready")
        # The backend must ignore an editor's uncommitted working copy.
        (directory / "visible-rule.md").write_text("Draft unrelated to dispatch")
        response = execute_tool(tool_code="memory.search", actor_context={"user_id": self.reader.pk},
                                payload={"query": "dispatch", "bundle_id": "manual", "sensitivity": "internal"},
                                request_id="scoped-memory-test")
        self.assertTrue(response["ok"], response)
        result = response["result"]
        self.assertEqual([i["knowledge_id"] for i in result["items"]], ["visible-rule"])
        self.assertEqual(result["items"][0]["citation_ids"], [result["citations"][0]["id"]])
        self.assertEqual(result["citations"][0]["snapshot_hash"], ready["revision"])
        self.assertNotIn("restricted", str(result))
        audit = MemoryAccessAudit.objects.get(request_id="scoped-memory-test")
        self.assertEqual(audit.policy_decision, "allowed")
        self.assertNotIn("dispatch", str(audit.retrieval_trace).lower())
        self.assertEqual(audit.returned_document_ids, [])
        action = AgentActionLog.objects.get(tool_code="memory.search", actor=self.reader)
        saved = str((action.request_payload, action.response_payload, ChatMessage.objects.get(
            tool_name="memory.search", session=action.session).metadata)).lower()
        for private_value in ("dispatch", "packing slip", "visible-rule", "restricted invoice"):
            self.assertNotIn(private_value, saved)
        item = MemoryKnowledgeItem.objects.get(memory_id="visible-rule")
        read = read_knowledge_for_actor(item=item, actor=self.reader, request_id="read-test")
        self.assertEqual(read["text"], result["items"][0]["text"])
        self.assertEqual(read["source_refs"], [ref])
        self.assertEqual(read["request_id"], "read-test")
        for overrides in ({"sensitivity": "public"}, {"sensitivity": "secret"}, {"corpus": "source_data"},
                          {"bundle_id": ""}):
            denied = execute_tool(tool_code="memory.search", actor_context={"user_id": self.reader.pk},
                                  payload={"query": "dispatch", "bundle_id": "manual", **overrides})
            self.assertFalse(denied["ok"])
        self.source.trust_status = "blocked"
        self.source.save()
        with self.assertRaises(PermissionDenied):
            read_knowledge_for_actor(item=item, actor=self.reader)
