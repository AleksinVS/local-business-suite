import os
import shutil
import subprocess
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings

from ..chat_memory import _index_knowledge_item_locked
from ..knowledge_files import read_knowledge_item_file, walk_all_knowledge_files
from ..models import MemoryKnowledgeItem, MemorySearchDocument, WikiBundleCheckpoint
from ..wiki_config import wiki_bundles
from ..wiki_reconcile import (
    WikiInventoryError, read_wiki_snapshot, reconcile_wiki_bundle, registered_wiki_notes, wiki_head,
    wiki_snapshot_ready,
)

pytestmark = pytest.mark.integration


class WikiReconcileTests(TestCase):
    def setUp(self):
        super().setUp()
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.actor = get_user_model().objects.create_user(username="wiki-projection")
        self.config = {"common": {"path": "org/crow/common", "projection_user_id": self.actor.pk,
                                  "read_tokens": ["group:wiki"], "note_read_tokens": {"denied": []}}}
        self.enterContext(override_settings(LOCAL_BUSINESS_WIKI_BUNDLES=self.config, DATA_DIR=self.root / "state"))
        self.enterContext(patch.dict(os.environ, {"LOCAL_BUSINESS_KNOWLEDGE_REPO_DIR": str(self.root)}))
        self.bundle = wiki_bundles()["common"]
        self.directory = self.root / self.bundle.path
        self.directory.mkdir(parents=True)
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.test")
        (self.directory / "index.md").write_text("# Wiki\n")
        self.commit()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root)

    def commit(self):
        self.git("add", "--", self.bundle.path)
        self.git("commit", "-qm", "Record Wiki changes")
        return wiki_head(self.root)

    def note(self, name, native="one", body="oldword", extra=""):
        path = self.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\ntype: Note\nid: {native}\ntitle: Note\n{extra}---\n\n{body}\n", encoding="utf-8")
        return path

    def run_reconcile(self, **kwargs):
        return reconcile_wiki_bundle(self.bundle, **kwargs)

    def command(self, **kwargs):
        stream = StringIO()
        call_command("memory_reconcile", wiki_bundle="common", stdout=stream, **kwargs)
        return stream.getvalue()

    def test_full_cycle_including_verified_empty_tree(self):
        file = self.note("subject.md")
        revision = self.commit()
        file.write_text("Uncommitted body")
        self.assertIn('"created": 1', self.command(dry_run=True))
        self.assertFalse(WikiBundleCheckpoint.objects.exists())
        self.assertFalse(MemoryKnowledgeItem.objects.exists())
        self.command(force=True)
        item = MemoryKnowledgeItem.objects.get()
        self.assertIn(item.memory_id, registered_wiki_notes(self.bundle, revision))
        self.assertEqual(read_wiki_snapshot(self.bundle).notes[item.memory_id].body, "oldword")
        self.assertEqual(self.run_reconcile()["updated"], 0)
        self.assertEqual(self.run_reconcile(force=True)["updated"], 1)
        self.note("subject.md", body="replacement")
        changed = self.commit()
        self.assertFalse(wiki_snapshot_ready(self.bundle, revision))
        self.assertEqual(self.run_reconcile()["updated"], 1)
        self.assertEqual(read_wiki_snapshot(self.bundle, changed).notes[item.memory_id].body, "replacement")
        file.rename(self.directory / "moved.md")
        self.commit()
        self.assertEqual(self.run_reconcile()["moved"], 1)
        item.refresh_from_db()
        self.assertTrue(item.knowledge_file_path.endswith("/moved.md"))
        (self.directory / "moved.md").unlink()
        empty = self.commit()
        self.assertEqual(self.run_reconcile(dry_run=True)["deleted"], 1)
        self.assertEqual(self.run_reconcile()["deleted"], 1)
        self.assertTrue(wiki_snapshot_ready(self.bundle, empty))
        self.assertEqual(registered_wiki_notes(self.bundle, empty), {})
        item.refresh_from_db()
        self.assertEqual(item.status, "deleted")
        self.assertEqual(self.git("status", "--porcelain"), b"")
        self.assertEqual(wiki_head(self.root), empty)

    def test_author_note_without_raw_survives_projection_rebuild(self):
        file = self.note("author.md", extra="knowledge_id: authored\ndescription: Authored note\n")
        revision = self.commit()
        published = file.read_bytes()
        self.note("staged.md", native="staged")
        self.git("add", str(self.directory / "staged.md"))
        file.write_text("Uncommitted author text", encoding="utf-8")
        before = {p.relative_to(self.directory): p.read_bytes()
                  for p in self.directory.rglob("*") if p.is_file()}
        index = self.git("ls-files", "--stage", "-z")
        for options in ({}, {"dry_run": True}, {"force": True}):
            self.command(**options)
            self.assertEqual(wiki_head(self.root), revision)
            self.assertEqual(self.git("ls-files", "--stage", "-z"), index)
            self.assertEqual({p.relative_to(self.directory): p.read_bytes()
                              for p in self.directory.rglob("*") if p.is_file()}, before)
        MemoryKnowledgeItem.objects.all().delete()
        WikiBundleCheckpoint.objects.all().delete()
        self.command(force=True)
        self.assertIn("authored", registered_wiki_notes(self.bundle, revision))
        self.assertEqual(self.git("show", f"HEAD:{self.bundle.path}/author.md"), published)
        self.assertEqual(wiki_head(self.root), revision)
        self.assertEqual(self.git("ls-files", "--stage", "-z"), index)
        self.assertEqual({p.relative_to(self.directory): p.read_bytes()
                          for p in self.directory.rglob("*") if p.is_file()}, before)

    def test_failed_inventory_never_withdraws_and_retry_recovers(self):
        self.note("good.md", extra="knowledge_id: registered\n")
        good = self.commit()
        self.command()
        (self.directory / "good.md").unlink()
        (self.directory / "broken.md").write_text("---\ntype: Note\nid: bad")
        self.commit()
        with self.assertRaises(CommandError):
            self.command()
        state = WikiBundleCheckpoint.objects.get()
        self.assertEqual((state.status, state.revision), ("error", good))
        self.assertFalse(registered_wiki_notes(self.bundle, good))
        self.assertEqual(MemoryKnowledgeItem.objects.get().status, "active")
        (self.directory / "broken.md").unlink()
        self.note("new.md", extra="knowledge_id: registered\n")
        self.commit()
        self.assertEqual(self.run_reconcile()["moved"], 1)
        shutil.rmtree(self.directory)
        self.commit()
        self.assertEqual(self.run_reconcile()["status"], "error")
        self.assertEqual(MemoryKnowledgeItem.objects.get().status, "active")

    def test_statuses_exclusions_untrusted_frontmatter_and_legacy_paths(self):
        self.note("current.md", extra="confirmation_state: confirmed\n")
        for key, extra in {
            "draft": "status: draft", "deprecated": "status: deprecated", "pending": "lifecycle: pending",
            "raised": "sensitivity: confidential", "denied": "knowledge_id: denied",
            "scope-policy": "scope_tokens: ['org:default']", "nested-policy": "metadata: {acl: {allow: staff}}",
            "private": "audience: private", "privacy-label": "privacy: local",
        }.items():
            self.note(f"{key}.md", native=key, extra=extra + "\n")
        for name in ("raw/private.md", "schemas/schema.md", ".archive/old.md", ".llmw2/cursor.md", ".hidden.md", "log.md"):
            self.note(name)
        (self.directory / "source.md").write_text("---\ntype: Source\n---\nPrivate source")
        (self.directory / "link.md").symlink_to(self.directory / "raw/private.md")
        revision = self.commit()
        self.command()
        self.assertEqual(len(read_wiki_snapshot(self.bundle).notes), 10)
        self.assertEqual(MemoryKnowledgeItem.objects.filter(status="quarantined").count(), 8)
        item = MemoryKnowledgeItem.objects.get(knowledge_file_path__endswith="/current.md")
        self.assertEqual(item.scope_tokens, [])
        self.assertEqual(item.metadata["confirmation_state"], "needs_confirmation")
        self.assertTrue(wiki_snapshot_ready(self.bundle, revision))
        self.assertEqual(walk_all_knowledge_files(root=self.root), [])
        with self.assertRaises(PermissionDenied):
            read_knowledge_item_file(item)
        self.assertEqual(_index_knowledge_item_locked(item)["skipped"], "wiki_projection")
        self.assertFalse(MemorySearchDocument.objects.exists())
        self.config["common"]["note_read_tokens"]["other"] = ["group:private"]
        self.assertFalse(wiki_snapshot_ready(wiki_bundles()["common"], revision))

    def test_id_collision_and_stale_inventory_fail_closed(self):
        self.note("a.md", extra="knowledge_id: existing\n")
        initial = self.commit()
        self.command()
        self.note("b.md", native="two", extra="knowledge_id: existing\n")
        self.commit()
        self.assertEqual(self.run_reconcile()["status"], "error")
        self.assertEqual(MemoryKnowledgeItem.objects.count(), 1)
        (self.directory / "b.md").unlink()
        self.note("a.md", extra="knowledge_id: swapped\n")
        self.commit()
        self.assertEqual(self.run_reconcile()["error"], "native_alias_conflict")
        self.note("a.md", extra="knowledge_id: existing\n", body="new")
        candidate = self.commit()
        with patch("apps.memory.wiki_reconcile.wiki_head", side_effect=[candidate, initial, candidate]):
            self.assertEqual(self.run_reconcile()["error"], "stale_revision")
        self.assertEqual(WikiBundleCheckpoint.objects.get().revision, initial)
        self.assertEqual(self.run_reconcile()["updated"], 1)

    def test_other_bundle_cannot_reuse_a_ready_checkpoint_or_a_native_id(self):
        self.note("one.md", native="shared")
        old = self.commit()
        self.assertEqual(self.run_reconcile()["created"], 1)
        self.config["other"] = dict(self.config["common"], path="org/crow/other")
        other = wiki_bundles()["other"]
        other_path = self.root / other.path
        other_path.mkdir()
        shutil.copyfile(self.directory / "one.md", other_path / "two.md")
        self.git("add", "--", other.path)
        self.git("commit", "-qm", "Other bundle")
        head = wiki_head(self.root)
        self.assertFalse(wiki_snapshot_ready(self.bundle, old))
        self.assertFalse(wiki_snapshot_ready(other, old))
        self.assertFalse(wiki_snapshot_ready(other, head))
        self.assertEqual(reconcile_wiki_bundle(other)["created"], 1)
        self.assertEqual(self.run_reconcile()["updated"], 1)
        self.assertFalse(set(registered_wiki_notes(other, head)) & set(registered_wiki_notes(self.bundle, head)))
        # An operator error mounting a different path under the same ID is never
        # treated as proof that the old bundle's articles have been deleted.
        missing = dict(self.config["common"], path="org/crow/missing")
        with override_settings(LOCAL_BUSINESS_WIKI_BUNDLES={"common": missing}):
            wrong = wiki_bundles()["common"]
            self.assertFalse(wiki_snapshot_ready(wrong, head))
            self.assertEqual(reconcile_wiki_bundle(wrong)["status"], "error")
        self.assertEqual(MemoryKnowledgeItem.objects.filter(status="active").count(), 2)

    def test_foreign_claim_hides_the_registered_owner_until_successful_repair(self):
        self.note("owned.md", extra="knowledge_id: disputed\n")
        self.commit()
        self.command()
        other = dict(self.config["common"], path="org/crow/other")
        self.config["other"] = other
        other_dir = self.root / other["path"]
        other_dir.mkdir()
        (other_dir / "index.md").write_text("# Other")
        (other_dir / "claim.md").write_bytes((self.directory / "owned.md").read_bytes())
        self.git("add", "--", other["path"])
        self.git("commit", "-qm", "Conflicting claim")
        head = wiki_head(self.root)
        self.command()
        claimant = wiki_bundles()["other"]
        self.assertEqual(reconcile_wiki_bundle(claimant)["error"], "global_id_conflict")
        self.assertFalse(registered_wiki_notes(self.bundle, head))
        self.assertFalse(registered_wiki_notes(claimant, head))
        (other_dir / "claim.md").unlink()
        self.git("add", "--", other["path"])
        self.git("commit", "-qm", "Withdraw conflicting claim")
        self.assertEqual(reconcile_wiki_bundle(claimant)["status"], "ready")
        self.command()
        self.assertIn("disputed", registered_wiki_notes(self.bundle, wiki_head(self.root)))

    def test_repository_unavailable_does_not_initialize_a_new_empty_canon(self):
        self.note("a.md")
        self.commit()
        self.command()
        absent = self.root / "unmounted_knowledge_repo"
        with patch.dict(os.environ, {"LOCAL_BUSINESS_KNOWLEDGE_REPO_DIR": str(absent)}):
            with self.assertRaises(CommandError):
                call_command("memory_reconcile", stdout=StringIO())
            self.assertFalse(absent.exists())
        self.assertEqual(MemoryKnowledgeItem.objects.get().status, "active")
        self.assertEqual(WikiBundleCheckpoint.objects.get().status, "error")

    def test_timer_does_not_consume_staging_or_expose_mixed_wiki_commits(self):
        self.note("a.md")
        legacy = self.root / "org" / "legacy.md"
        legacy.write_text("Regular legacy article")
        self.git("add", ".")
        self.git("commit", "-qm", "Private subject mixed with legacy")
        self.note("staged.md", native="staged")
        self.git("add", str(self.directory / "staged.md"))
        index = self.git("diff", "--cached")
        call_command("memory_reconcile", stdout=StringIO())
        self.assertEqual(self.git("diff", "--cached"), index)
        self.assertEqual(MemoryKnowledgeItem.objects.count(), 1)
        self.assertNotIn("Private subject", (self.root / "org/log.md").read_text())
        self.assertNotIn("oldword", (self.root / "org/index.md").read_text())
