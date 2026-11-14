import os
import subprocess
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
import yaml
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import DatabaseError
from django.test import TestCase, override_settings

from apps.ai.models import AgentActionLog, ChatMessage
from apps.ai.skills_service import discover_skills
from apps.ai.tooling import execute_tool
from apps.memory.models import MemorySearchDocument, MemorySource, MemorySourceObject
from apps.memory.wiki_reconcile import wiki_head
from services.agent_runtime.tools import build_tools

from .test_contract_gateway import ai_policy_snapshot


@pytest.mark.integration
class WikiAgentFlowTests(TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, {"LOCAL_BUSINESS_KNOWLEDGE_REPO_DIR": str(self.root)}))
        self.author = get_user_model().objects.create_user("wiki-maintainer")
        self.other = get_user_model().objects.create_superuser("other-user")
        token = f"user:{self.author.pk}"
        self.bundle = dict(path="org/crow/manuals", projection_user_id=self.author.pk,
                           read_tokens=[token], write_tokens=[token], model_context=True)
        self.enterContext(override_settings(LOCAL_BUSINESS_WIKI_BUNDLES={"manuals": self.bundle},
                                           LOCAL_BUSINESS_MEMORY_TEST_SOURCE_ALLOWLIST=("wiki-reference",),
                                           LOCAL_BUSINESS_WIKI_SEARCH="basic"))
        self.dir = self.root / self.bundle["path"]
        self.dir.mkdir(parents=True)
        (self.dir / "index.md").write_text('---\nokf_version: "0.2"\n---\n\n# Notes\n')
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@localhost")
        self.commit()
        call_command("memory_reconcile", wiki_bundle="manuals")
        src = MemorySource.objects.create(code="wiki-reference", title="Approved reference", source_kind="file_share",
                                          sensitivity="internal", trust_status="trusted", trusted_for_context=True,
                                          authority_class="approved_corpus", trusted_context_kinds=["retrieved_chunk","citation"])
        text = "The maintenance interval for a pressure valve is five weeks."
        h = sha256(text.encode()).hexdigest()
        self.obj = MemorySourceObject.objects.create(source=src, object_id="valve-schedule", content_hash=h,
                      ingestion_status="ingested", discovery_status="seen",
                      metadata={"scope_tokens":["org:default"], "safe_text":text})
        MemorySearchDocument.objects.create(document_id="valve-doc", corpus_type="source_data",
                   object_kind="source_object", index_status="ready", source_object=self.obj, body_hash=h,
                   metadata={"content_hash":h,"sensitivity":"internal","safe_text_hash":h})
        self.snapshot = ai_policy_snapshot()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root)

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")

    def run_tool(self, action, actor=None, **payload):
        return execute_tool(tool_code="knowledge."+action, actor_context={"user_id": (actor or self.author).pk},
                            payload=payload, contract_snapshot=self.snapshot)

    def ok(self, action, **payload):
        result = self.run_tool(action, **payload)
        self.assertTrue(result["ok"], result["errors"])
        return result["result"]

    def test_author_skill_reads_sources_and_publishes_one_searchable_commit(self):
        self.assertIn("wiki-author", [v["id"] for v in discover_skills(use_cache=False)])
        runtime = build_tools(actor={}, session_id="", gateway_client=None, contract_snapshot=self.snapshot)
        self.assertIn("knowledge.edit", {tool.name for tool in runtime})
        self.assertEqual(self.ok("search"), {"bundles":["manuals"]})
        self.assertEqual(self.run_tool("search", self.other)["result"], {"bundles":[]})
        source = self.ok("source", bundle_id="manuals", source_code="wiki-reference", source_object_id="valve-schedule")
        base = self.ok("search", bundle_id="manuals")["revision"]
        docs = {}
        for key, body in (("schedule", "Needlevalve interval. See [Guide](guide.md)."),
                          ("guide", "Read the [schedule](schedule.md).")):
            meta = dict(type="Note", knowledge_id=key, title=key.title(), description="Maintenance",
                        source_refs=[source["source_ref"]])
            docs[f"{key}.md"] = "---\n"+yaml.safe_dump(meta,sort_keys=False)+"---\n\n"+body+"\n"
        args = dict(bundle_id="manuals", expected_revision=base, files=docs)
        with patch("apps.memory.wiki_gateway.reconcile_wiki_bundle", side_effect=DatabaseError("unavailable")):
            result = self.ok("edit", **args)
        self.assertEqual(result["index_status"], "index_pending")
        self.assertEqual(self.git("rev-parse", "HEAD^").decode().strip(), base)
        retry = self.ok("edit", **args)
        self.assertFalse(retry["committed"])
        self.assertEqual(retry["index_status"], "ready")
        self.assertEqual(result["revision"], retry["revision"])
        self.assertEqual(self.ok("search", bundle_id="manuals", query="needlevalve")["items"][0]["knowledge_id"], "schedule")
        self.assertEqual(self.ok("get", bundle_id="manuals", knowledge_id="schedule")["markdown"],docs["schedule.md"])
        self.assertEqual(self.ok("get", bundle_id="manuals", path="guide.md")["knowledge_id"], "guide")
        self.assertFalse(self.run_tool("get", self.other, bundle_id="manuals", knowledge_id="schedule")["ok"])
        self.assertNotIn("Needlevalve", str(list(AgentActionLog.objects.values("request_payload","response_payload"))))
        self.assertNotIn("Needlevalve", str(list(ChatMessage.objects.values("metadata"))))
        with patch("apps.memory.wiki_gateway.classify_proposed_change",
                   return_value={"relation": "extends", "probability": 0.9, "model": "fixture"}) as classifier:
            change = self.ok("compare", bundle_id="manuals", left_id="schedule",
                             proposed_text="Inspect the second valve too.", source_ref=source["source_ref"])
            self.assertEqual(change["relation"], "extends")
            self.assertEqual(classifier.call_args.args[0].knowledge_id, "schedule")
            self.assertEqual(wiki_head(self.root), result["revision"])
        self.obj.source.status = "disabled"
        self.obj.source.save()
        self.assertEqual(self.ok("search", bundle_id="manuals", query="needlevalve")["items"],[])
        self.assertFalse(self.run_tool("get", bundle_id="manuals", knowledge_id="schedule")["ok"])

    def test_external_commit_visibility_and_mixed_acl_before_rank(self):
        def note(key, body):
            return f"---\ntype: Note\nknowledge_id: {key}\ntitle: {key}\ndescription: Reference\n---\n\n{body}\n"
        (self.dir / "public.md").write_text(note("public", "term"))
        (self.dir / "closed.md").write_text(note("closed", "term term term"))
        (self.dir / "linked.md").write_text(note("linked", "term [secret topic](closed.md)"))
        (self.dir / "indirect.md").write_text(note("indirect", "term [see neighbor](linked.md)"))
        self.assertEqual(self.ok("search", bundle_id="manuals", query="term")["items"], [])
        self.commit()
        self.bundle["note_read_tokens"] = {"closed":[]}
        self.assertFalse(self.run_tool("search", bundle_id="manuals", query="term")["ok"])
        call_command("memory_reconcile", wiki_bundle="manuals")
        seen = self.ok("search", bundle_id="manuals", query="term", limit=1)
        self.assertEqual([i["knowledge_id"] for i in seen["items"]],["public"])
        for hidden in ("closed", "linked", "indirect"):
            self.assertFalse(self.run_tool("get", bundle_id="manuals", knowledge_id=hidden)["ok"])
        self.assertFalse(self.run_tool("get", bundle_id="manuals", path="closed.md")["ok"])
        with patch("apps.memory.wiki_gateway.classify_crow_relation") as classifier:
            self.assertFalse(self.run_tool("compare", bundle_id="manuals", left_id="public", right_id="closed")["ok"])
            classifier.assert_not_called()
        self.assertFalse(self.run_tool("edit", bundle_id="manuals", expected_revision=wiki_head(self.root),
                                       files={"closed.md": None})["ok"])

    def test_wrong_source_version_does_not_create_git_commit(self):
        sha = wiki_head(self.root)
        ref = self.ok("source", bundle_id="manuals", source_code="wiki-reference", source_object_id="valve-schedule")["source_ref"]
        ref["text_hash"] = "a"*64
        meta = dict(type="Note", knowledge_id="article", title="Manual", description="Inspection", source_refs=[ref])
        md = "---\n"+yaml.safe_dump(meta)+"---\n\nInspect the valve.\n"
        result = self.run_tool("edit", bundle_id="manuals", expected_revision=sha, files={"article.md":md})
        self.assertFalse(result["ok"])
        self.assertEqual(wiki_head(self.root), sha)
