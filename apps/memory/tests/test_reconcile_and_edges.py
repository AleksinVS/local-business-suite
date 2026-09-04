"""Тесты reconcile канона, repo lock и словаря рёбер."""
from copy import deepcopy
from dataclasses import replace

from apps.memory.tests._common import *  # noqa: F401,F403


class KnowledgeRepoLockTests(TestCase):
    """Cross-platform single-writer lock for the knowledge repository.

    ADR-0030 decision 2: the write lock must really exclude a second writer on
    both Linux and Windows (the old fcntl-only lock was a no-op on Windows).
    """

    def test_lock_excludes_concurrent_writer(self):
        import threading

        from ..knowledge_files import knowledge_repo_lock

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            order = []
            second_acquired = threading.Event()

            def second_writer():
                with knowledge_repo_lock(root):
                    order.append("second")
                    second_acquired.set()

            with knowledge_repo_lock(root):
                order.append("first")
                worker = threading.Thread(target=second_writer)
                worker.start()
                # Second writer must not acquire the lock while we hold it.
                self.assertFalse(second_acquired.wait(timeout=0.5))
                self.assertEqual(order, ["first"])

            # After release the second writer proceeds.
            worker.join(timeout=5)
            self.assertTrue(second_acquired.is_set())
            self.assertEqual(order, ["first", "second"])


class MemoryReconcileTests(TestCase):
    """Pull reconciler and file-as-canon behavior (ADR-0030 P01)."""

    databases = RUNTIME_DATABASES

    def _make_item(self):
        from apps.ai.models import ChatMessage, ChatSession

        from ..chat_memory import remember_knowledge

        user = User.objects.create_user(username="reconcile-user", password="pass")
        session = ChatSession.objects.create(user=user, title="Memory chat")
        message = ChatMessage.objects.create(
            session=session, role=ChatMessage.Role.USER, content="Запомни: alpha требует калибровку."
        )
        result = remember_knowledge(
            actor=user, session=session, payload={"message_ids": [message.id]}, request_id="req-reconcile"
        )
        return user, MemoryKnowledgeItem.objects.get(memory_id=result["memory_id"])

    def _rewrite_file(self, item, *, body=None, metadata_updates=None):
        from ..knowledge_files import (
            KnowledgeFile,
            _safe_repo_path,
            knowledge_repo_root,
            parse_knowledge_file,
            render_knowledge_file,
        )

        path = _safe_repo_path(knowledge_repo_root(), item.knowledge_file_path)
        parsed = parse_knowledge_file(path.read_text(encoding="utf-8"))
        meta = dict(parsed.metadata)
        if metadata_updates:
            meta.update(metadata_updates)
        new = KnowledgeFile(metadata=meta, body=body if body is not None else parsed.body)
        path.write_text(render_knowledge_file(new), encoding="utf-8")

    def test_manual_body_edit_reconciles_without_read_error(self):
        from ..knowledge_files import read_knowledge_item_file, sha256_text

        with TemporaryDirectory() as tmpdir, self.settings(
            DATA_DIR=Path(tmpdir), LOCAL_BUSINESS_MEMORY_FILE_CANON_AUTHORITATIVE=True
        ):
            _user, item = self._make_item()
            new_body = "alpha калибруется ежемесячно reconciletoken777"
            self._rewrite_file(item, body=new_body)

            # Canon inversion: a manual edit must not break reads.
            self.assertIn("reconciletoken777", read_knowledge_item_file(item).body)

            out = StringIO()
            call_command("memory_reconcile", stdout=out)
            item.refresh_from_db()
            self.assertEqual(item.text_hash, sha256_text(new_body))
            self.assertIn("reconciled=1", out.getvalue())

            # Idempotency: a second run with no changes reports zero reconciled.
            out2 = StringIO()
            call_command("memory_reconcile", stdout=out2)
            self.assertIn("reconciled=0", out2.getvalue())

    def test_reconcile_holds_profiles_and_graph_snapshot_across_item_loop(self):
        """A mid-run repository change must affect only the next operation."""
        from types import SimpleNamespace

        with TemporaryDirectory() as tmpdir, self.settings(
            DATA_DIR=Path(tmpdir), LOCAL_BUSINESS_MEMORY_FILE_CANON_AUTHORITATIVE=True
        ):
            _user, item = self._make_item()
            self._rewrite_file(item, body="snapshot loop marker 2026")
            from apps.memory.config_documents import get_memory_document_snapshots

            base = get_memory_document_snapshots(
                document_ids=(
                    "memory.contract.profiles",
                    "memory.contract.graph_schema",
                )
            )
            profiles_v1 = replace(
                base["memory.contract.profiles"],
                payload={**deepcopy(base["memory.contract.profiles"].payload), "test_revision": "v1"},
            )
            graph_v1 = replace(
                base["memory.contract.graph_schema"],
                payload={**deepcopy(base["memory.contract.graph_schema"].payload), "test_revision": "v1"},
            )
            profiles_v2 = replace(
                profiles_v1,
                revision=profiles_v1.revision + 1,
                payload={**deepcopy(profiles_v1.payload), "test_revision": "v2"},
            )
            graph_v2 = replace(
                graph_v1,
                revision=graph_v1.revision + 1,
                payload={**deepcopy(graph_v1.payload), "test_revision": "v2"},
            )
            current = {"snapshots": {"memory.contract.profiles": profiles_v1, "memory.contract.graph_schema": graph_v1}}
            reader_calls = []
            indexed = []
            materialized = []

            def read_snapshots(*, document_ids=None, request=None):
                reader_calls.append(tuple(document_ids or ()))
                return current["snapshots"]

            def index_with_mutation(indexed_item, *, snapshots=None):
                indexed.append(snapshots)
                current["snapshots"] = {
                    "memory.contract.profiles": profiles_v2,
                    "memory.contract.graph_schema": graph_v2,
                }

            fake_edges = SimpleNamespace(created=0, updated=0, deleted=0, skipped=[])
            with patch(
                "apps.memory.management.commands.memory_reconcile.get_memory_document_snapshots",
                side_effect=read_snapshots,
            ), patch(
                "apps.memory.management.commands.memory_reconcile.index_knowledge_item",
                side_effect=index_with_mutation,
            ), patch(
                "apps.memory.management.commands.memory_reconcile.materialize_knowledge_edges",
                side_effect=lambda **kwargs: materialized.append(kwargs.get("snapshots")) or fake_edges,
            ), patch(
                "apps.memory.management.commands.memory_reconcile.rebuild_all_knowledge_indexes",
                return_value=[],
            ), patch(
                "apps.memory.management.commands.memory_reconcile.rebuild_all_knowledge_logs",
                return_value=[],
            ):
                call_command("memory_reconcile", verbosity=0)
                self.assertEqual(len(reader_calls), 1)
                self.assertEqual(indexed[0]["memory.contract.profiles"].payload["test_revision"], "v1")
                self.assertEqual(materialized[0]["memory.contract.graph_schema"].payload["test_revision"], "v1")

                call_command("memory_reconcile", verbosity=0)
            self.assertEqual(len(reader_calls), 2)
            self.assertEqual(materialized[1]["memory.contract.graph_schema"].payload["test_revision"], "v2")

    def test_manual_sensitivity_downgrade_is_held_pending(self):
        with TemporaryDirectory() as tmpdir, self.settings(
            DATA_DIR=Path(tmpdir), LOCAL_BUSINESS_MEMORY_FILE_CANON_AUTHORITATIVE=True
        ):
            _user, item = self._make_item()
            item.sensitivity = "confidential"
            item.save(update_fields=["sensitivity"])

            # Manual edit lowers the classification: must not apply silently.
            self._rewrite_file(item, metadata_updates={"sensitivity": "public"})
            out = StringIO()
            call_command("memory_reconcile", stdout=out)
            item.refresh_from_db()
            self.assertEqual(item.sensitivity, "confidential")
            self.assertIn("held=1", out.getvalue())
            self.assertEqual((item.metadata or {}).get("lifecycle"), "pending")

    def test_frontmatter_has_no_derived_state(self):
        from ..knowledge_files import _safe_repo_path, knowledge_repo_root, parse_knowledge_file

        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            _user, item = self._make_item()
            path = _safe_repo_path(knowledge_repo_root(), item.knowledge_file_path)
            meta = parse_knowledge_file(path.read_text(encoding="utf-8")).metadata
            # Invariant #9: derived-layer state stays out of the canon.
            self.assertNotIn("index_status", meta)
            self.assertNotIn("text_hash", meta)
            self.assertEqual(meta.get("lifecycle"), "current")

    def test_reconcile_regenerates_index_md_from_files_not_summary_md(self):
        """ADR-0030 decision 4: index.md is generated from the knowledge files
        on disk by the reconciler; _summary.md is no longer produced anywhere."""
        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            user, item = self._make_item()

            out = StringIO()
            call_command("memory_reconcile", stdout=out)
            self.assertIn("indexes_written=", out.getvalue())

            index_path = Path(tmpdir) / "knowledge_repo" / "users" / str(user.id) / "index.md"
            summary_path = Path(tmpdir) / "knowledge_repo" / "users" / str(user.id) / "_summary.md"
            self.assertTrue(index_path.exists())
            self.assertFalse(summary_path.exists())
            self.assertIn(item.memory_id, index_path.read_text(encoding="utf-8"))

            org_index_path = Path(tmpdir) / "knowledge_repo" / "org" / "index.md"
            org_summary_path = Path(tmpdir) / "knowledge_repo" / "org" / "_summary.md"
            self.assertTrue(org_index_path.exists())
            self.assertFalse(org_summary_path.exists())

    def test_reconcile_regenerates_log_md_from_git_deterministically(self):
        """ADR-0030 decision 4: log.md is generated from git log, never
        hand-edited, and regenerating with no new commits is byte-identical
        (the file excludes its own commit history from the query so it does
        not grow every time it is regenerated)."""
        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            user, item = self._make_item()

            out = StringIO()
            call_command("memory_reconcile", stdout=out)
            self.assertIn("logs_written=", out.getvalue())

            log_path = Path(tmpdir) / "knowledge_repo" / "users" / str(user.id) / "log.md"
            self.assertTrue(log_path.exists())
            first_content = log_path.read_text(encoding="utf-8")
            self.assertIn("Remember knowledge", first_content)

            out2 = StringIO()
            call_command("memory_reconcile", stdout=out2)
            second_content = log_path.read_text(encoding="utf-8")
            self.assertEqual(first_content, second_content)

            org_log_path = Path(tmpdir) / "knowledge_repo" / "org" / "log.md"
            self.assertTrue(org_log_path.exists())


class MemoryKnowledgeEdgeTests(TestCase):
    """Deterministic `relations:` edge materializer (ADR-0030 decision 3, packet 05).

    Replaces the removed LLM graph-extraction contour: typed edges come from
    a knowledge file's `relations:` frontmatter, validated against the
    controlled edge-type vocabulary (contracts/ai/memory_graph_schema.json)
    and materialized into MemoryKnowledgeEdge by memory_reconcile — no LLM."""

    databases = RUNTIME_DATABASES

    def _make_item(self, *, tag):
        from apps.ai.models import ChatMessage, ChatSession

        from ..chat_memory import remember_knowledge

        user = User.objects.create_user(username=f"edge-user-{tag}", password="pass")
        session = ChatSession.objects.create(user=user, title="Memory chat")
        message = ChatMessage.objects.create(
            session=session, role=ChatMessage.Role.USER, content=f"Запомни: concept {tag} note."
        )
        result = remember_knowledge(
            actor=user, session=session, payload={"message_ids": [message.id]}, request_id=f"req-edge-{tag}"
        )
        return user, MemoryKnowledgeItem.objects.get(memory_id=result["memory_id"])

    def _rewrite_relations(self, item, relations):
        from ..knowledge_files import (
            KnowledgeFile,
            _safe_repo_path,
            knowledge_repo_root,
            parse_knowledge_file,
            render_knowledge_file,
        )

        path = _safe_repo_path(knowledge_repo_root(), item.knowledge_file_path)
        parsed = parse_knowledge_file(path.read_text(encoding="utf-8"))
        meta = dict(parsed.metadata)
        meta["relations"] = relations
        new = KnowledgeFile(metadata=meta, body=parsed.body)
        path.write_text(render_knowledge_file(new), encoding="utf-8")

    def test_valid_relation_produces_knowledge_edge_after_reconcile(self):
        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            _source_user, source_item = self._make_item(tag="source")
            _target_user, target_item = self._make_item(tag="target")

            self._rewrite_relations(
                source_item,
                [
                    {
                        "type": "depends_on",
                        "target": target_item.memory_id,
                        "provenance": "source_code:workorders_public_timeline",
                    }
                ],
            )

            out = StringIO()
            call_command("memory_reconcile", stdout=out)
            self.assertIn("edges_created=1", out.getvalue())

            edge = MemoryKnowledgeEdge.objects.get(
                source_path=source_item.knowledge_file_path,
                edge_type="depends_on",
                target=target_item.memory_id,
            )
            self.assertEqual(edge.source_knowledge_id, source_item.memory_id)
            self.assertEqual(edge.target_path, target_item.knowledge_file_path)
            self.assertEqual(edge.target_knowledge_id, target_item.memory_id)
            self.assertEqual(edge.provenance, "source_code:workorders_public_timeline")

    def test_unknown_edge_type_rejected_with_clear_error(self):
        from ..knowledge_edges import validate_relation_entry

        with self.assertRaises(ValidationError) as ctx:
            validate_relation_entry(
                {"type": "not_a_real_relation", "target": "some/concept.md", "provenance": "source_code:some/path"}
            )
        self.assertIn("not_a_real_relation", str(ctx.exception))

    def test_pending_edge_type_not_yet_accepted_is_rejected(self):
        """A type present in the vocabulary with status=proposed (not yet
        reviewed/accepted by the graph owner) is not usable in `relations:`
        yet — the moderated-schema expansion gate (ADR-0004 mechanic, carried
        by the contract's `status` field instead of the removed
        MemoryGraphSchemaProposal/MemoryGraphReviewItem tables)."""
        from ..knowledge_edges import validate_relation_entry

        with self.assertRaises(ValidationError):
            validate_relation_entry(
                {"type": "duplicates", "target": "some/concept.md", "provenance": "source_code:some/path"}
            )

    def test_invalid_relation_provenance_rejected_with_clear_error(self):
        from ..knowledge_edges import validate_relation_entry

        with self.assertRaises(ValidationError) as ctx:
            validate_relation_entry(
                {"type": "relates_to", "target": "some/concept.md", "provenance": "see the report"}
            )
        self.assertIn("provenance", str(ctx.exception))

    def test_full_rebuild_is_deterministic(self):
        from ..knowledge_edges import materialize_knowledge_edges

        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            _source_user, source_item = self._make_item(tag="rebuild-source")
            _target_user, target_item = self._make_item(tag="rebuild-target")
            self._rewrite_relations(
                source_item,
                [
                    {
                        "type": "relates_to",
                        "target": target_item.memory_id,
                        "provenance": "source_code:workorders_public_timeline",
                    }
                ],
            )

            first_result = materialize_knowledge_edges()
            self.assertEqual(first_result.created, 1)
            first_rows = sorted(
                MemoryKnowledgeEdge.objects.values_list("source_path", "edge_type", "target", "provenance")
            )

            second_result = materialize_knowledge_edges()
            self.assertEqual((second_result.created, second_result.updated, second_result.deleted), (0, 0, 0))
            second_rows = sorted(
                MemoryKnowledgeEdge.objects.values_list("source_path", "edge_type", "target", "provenance")
            )
            self.assertEqual(first_rows, second_rows)

    def test_reconcile_dry_run_reports_edge_counts_without_writing(self):
        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            _source_user, source_item = self._make_item(tag="dry-source")
            _target_user, target_item = self._make_item(tag="dry-target")
            self._rewrite_relations(
                source_item,
                [
                    {
                        "type": "relates_to",
                        "target": target_item.memory_id,
                        "provenance": "source_code:workorders_public_timeline",
                    }
                ],
            )

            out = StringIO()
            call_command("memory_reconcile", "--dry-run", stdout=out)
            self.assertIn("edges_created=1", out.getvalue())
            self.assertEqual(MemoryKnowledgeEdge.objects.count(), 0)

    def test_invalid_relation_entry_is_skipped_not_fatal_for_the_whole_run(self):
        """One bad relation in a file must not block reconciling the rest of
        the repo (soft degradation, concept v0.5 §7.1)."""
        from ..knowledge_edges import materialize_knowledge_edges

        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            _source_user, source_item = self._make_item(tag="mixed-source")
            _target_user, target_item = self._make_item(tag="mixed-target")
            self._rewrite_relations(
                source_item,
                [
                    {
                        "type": "relates_to",
                        "target": target_item.memory_id,
                        "provenance": "source_code:workorders_public_timeline",
                    },
                    {"type": "not_a_real_relation", "target": target_item.memory_id, "provenance": "source_code:x"},
                ],
            )

            result = materialize_knowledge_edges()
            self.assertEqual(result.created, 1)
            self.assertEqual(len(result.skipped), 1)
            self.assertIn("not_a_real_relation", result.skipped[0]["error"])
            self.assertTrue(
                MemoryKnowledgeEdge.objects.filter(edge_type="relates_to", target=target_item.memory_id).exists()
            )
