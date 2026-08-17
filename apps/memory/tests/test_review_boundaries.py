"""Регрессионные проверки границ очереди ревью памяти."""

import os
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import PermissionDenied

from apps.memory.tests._common import *  # noqa: F401,F403
from apps.memory.policies import (
    can_access_search_document,
    can_review_scoped_issue,
    can_manage_memory,
    can_view_memory_review_queue,
    source_object_scope_tokens,
    resolve_active_actor,
)
from apps.memory.services import can_access_source_object, can_access_source_object_via_adapter
from apps.memory.knowledge_files import write_knowledge_item_file
from apps.memory.review_services import accept_pending_item
from apps.memory.review_selectors import (
    _scoped_index_job_queryset,
    assignees_for_issue,
    issue_detail_context,
    issue_to_review_queue_item,
    search_document_detail_context,
    source_filter_options,
)
from apps.memory.selectors import (
    active_search_documents_queryset,
    memory_sources_queryset,
    recent_index_jobs_queryset,
    search_documents_for_source_queryset,
)


class MemoryReviewBoundaryTests(MemoryModelFactoryMixin, TestCase):
    databases = RUNTIME_DATABASES

    def review_operator(self, username="boundary-operator"):
        user = User.objects.create_user(username=username, password="pass")
        group, _ = Group.objects.get_or_create(name="memory_admin")
        user.groups.add(group)
        return user

    def test_inactive_superuser_and_operator_cannot_read_or_act(self):
        root = User.objects.create_superuser(username="inactive-root", password="pass")
        root.is_active = False
        root.save(update_fields=["is_active"])
        operator = self.review_operator("inactive-operator")
        operator.is_active = False
        operator.save(update_fields=["is_active"])

        self.assertFalse(can_view_memory_review_queue(root))
        self.assertFalse(can_view_memory_review_queue(operator))
        self.assertEqual(user_scope_tokens(root), set())
        self.assertEqual(user_scope_tokens(operator), set())

        from apps.memory.retrieval import memory_search

        with self.assertRaises(PermissionDenied):
            memory_search(actor=root, query="inactive memory query")

    def test_disabled_source_is_hidden_from_root_review_and_raw_selectors(self):
        root = User.objects.create_superuser(username="disabled-source-root", password="pass")
        source = self.create_source(code="disabled-review-source")
        source_object = MemorySourceObject.objects.create(
            source=source,
            object_id="disabled-object",
            object_uri="source://disabled-object",
            relative_path="disabled.txt",
            file_name="disabled.txt",
            metadata={"scope_tokens": ["org:default"]},
        )
        document = MemorySearchDocument.objects.create(
            document_id="disabled-review-document",
            corpus_type=MemorySearchDocument.CorpusType.SOURCE_DATA,
            object_kind=MemorySearchDocument.ObjectKind.SOURCE_OBJECT,
            source_object=source_object,
            index_status=MemorySearchDocument.IndexStatus.READY,
        )
        issue = MemoryIngestionIssue.objects.create(
            source=source,
            source_object=source_object,
            issue_kind=MemoryIngestionIssue.IssueKind.INDEX_FAILED,
            severity=MemoryIngestionIssue.Severity.ERROR,
            message="disabled source issue",
        )
        job = MemoryExternalConnectorJob.objects.create(
            source_code=source.code,
            job_kind=MemoryQueueJobKind.REINDEX,
            status="pending",
            idempotency_key="disabled-review-job",
            payload={"source_object_id": source_object.object_id},
        )
        source.status = MemorySource.Status.DISABLED
        source.save(update_fields=["status", "updated_at"])

        self.assertFalse(can_access_source_object(root, source_object))
        self.assertFalse(can_access_source_object_via_adapter(root, source_object))
        self.assertFalse(can_access_search_document(root, document))
        self.assertFalse(can_review_scoped_issue(root, issue))
        self.assertNotIn(issue, list(review_issue_queryset(root)))
        self.assertNotIn(document, list(index_document_queryset(root)))
        self.assertNotIn(job, list(_scoped_index_job_queryset(root)))
        self.assertEqual(list(memory_sources_queryset(root)), [])
        self.assertEqual(list(active_search_documents_queryset(root)), [])
        self.assertEqual(list(search_documents_for_source_queryset(source, root)), [])
        self.assertEqual(recent_index_jobs_queryset(root), [])
        self.assertEqual(list(source_filter_options(root)), [])
        self.assertEqual(list(source_filter_options()), [])

    def test_staff_and_django_permission_do_not_grant_memory_operator_authority(self):
        staff = User.objects.create_user(username="staff-only", password="pass", is_staff=True)
        self.assertFalse(can_manage_memory(staff))
        self.assertFalse(can_view_memory_review_queue(staff))

    def test_read_policy_refreshes_stale_actor_after_deactivate_and_group_revoke(self):
        actor = self.review_operator("stale-read-actor")
        self.assertTrue(can_view_memory_review_queue(actor))
        actor.is_active = False
        actor.save(update_fields=["is_active"])
        self.assertFalse(can_view_memory_review_queue(actor))

        actor.is_active = True
        actor.save(update_fields=["is_active"])
        self.assertTrue(can_view_memory_review_queue(actor))
        actor.groups.clear()
        self.assertFalse(can_view_memory_review_queue(actor))

    def test_contract_roles_and_technical_groups_use_different_scope_token_prefixes(self):
        role_user = User.objects.create_user(username="contract-role-user", password="pass")
        technical_user = self.review_operator("technical-group-user")
        role_user.groups.add(Group.objects.get_or_create(name=ROLE_MANAGER)[0])

        self.assertIn(f"role:{ROLE_MANAGER}", user_scope_tokens(role_user))
        self.assertNotIn(f"group:{ROLE_MANAGER}", user_scope_tokens(role_user))
        self.assertIn("group:memory_admin", user_scope_tokens(technical_user))
        self.assertNotIn("role:memory_admin", user_scope_tokens(technical_user))

    def test_adapter_check_filters_two_same_scope_objects_and_is_rechecked_by_service(self):
        actor = self.review_operator()
        source = self.create_source(
            code="boundary_adapter",
            config={"access_policy": {"mode": "adapter_check"}},
        )
        allowed_object = MemorySourceObject.objects.create(
            source=source,
            object_id="allowed",
            object_uri="source://allowed",
            relative_path="allowed.txt",
            file_name="allowed.txt",
            metadata={"scope_tokens": ["org:default"], "access_policy": {"mode": "adapter_check"}},
        )
        denied_object = MemorySourceObject.objects.create(
            source=source,
            object_id="denied",
            object_uri="source://denied",
            relative_path="denied.txt",
            file_name="denied.txt",
            metadata={"scope_tokens": ["org:default"], "access_policy": {"mode": "adapter_check"}},
        )
        allowed_document = MemorySearchDocument.objects.create(
            document_id="source:boundary-allowed",
            corpus_type=MemorySearchDocument.CorpusType.SOURCE_DATA,
            object_kind=MemorySearchDocument.ObjectKind.SOURCE_OBJECT,
            source_object=allowed_object,
            index_status=MemorySearchDocument.IndexStatus.READY,
        )
        denied_document = MemorySearchDocument.objects.create(
            document_id="source:boundary-denied",
            corpus_type=MemorySearchDocument.CorpusType.SOURCE_DATA,
            object_kind=MemorySearchDocument.ObjectKind.SOURCE_OBJECT,
            source_object=denied_object,
            index_status=MemorySearchDocument.IndexStatus.READY,
        )
        adapter = SimpleNamespace(can_access=lambda _user, object_id: str(object_id) == "allowed")
        with patch("apps.memory.services.get_source_adapter", return_value=adapter):
            documents = list(index_document_queryset(actor))
            self.assertIn(allowed_document, documents)
            self.assertNotIn(denied_document, documents)
            with self.assertRaises(PermissionDenied):
                apply_index_review_action(
                    actor=actor,
                    document=denied_document,
                    action="enqueue_reindex",
                )

    def test_source_wide_issue_and_empty_source_job_do_not_inherit_one_object_access(self):
        actor = self.review_operator("source-boundary-operator")
        source = self.create_source(
            code="source-wide-boundary",
            scope_rule="manual_scope_mapping",
            config={"scope_tokens": ["group:restricted"]},
        )
        visible_object = MemorySourceObject.objects.create(
            source=source,
            object_id="one-visible-object",
            object_uri="source://one-visible-object",
            relative_path="one.txt",
            file_name="one.txt",
            metadata={"scope_tokens": ["org:default"]},
        )
        issue = MemoryIngestionIssue.objects.create(
            source=source,
            issue_kind=MemoryIngestionIssue.IssueKind.INDEX_FAILED,
            severity=MemoryIngestionIssue.Severity.ERROR,
            message="source-wide issue",
        )
        job = MemoryExternalConnectorJob.objects.create(
            source_code="",
            job_kind=MemoryQueueJobKind.REINDEX,
            status="pending",
            idempotency_key="empty-source-boundary-job",
            payload={"source_object_id": visible_object.object_id},
        )

        self.assertNotIn(issue, list(review_issue_queryset(actor)))
        self.assertNotIn(job, list(_scoped_index_job_queryset(actor)))

    def test_source_wide_selector_refreshes_marked_actor_after_group_revoke(self):
        from apps.memory.review_selectors import review_issue_queryset

        actor = self.review_operator("stale-source-wide-actor")
        restricted, _ = Group.objects.get_or_create(name="stale-source-wide")
        actor.groups.add(restricted)
        source = self.create_source(
            code="stale-source-wide",
            scope_rule="manual_scope_mapping",
            config={"scope_tokens": ["group:stale-source-wide"]},
        )
        issue = MemoryIngestionIssue.objects.create(
            source=source,
            issue_kind=MemoryIngestionIssue.IssueKind.INDEX_FAILED,
            severity=MemoryIngestionIssue.Severity.ERROR,
            message="source-wide stale actor",
        )
        marked = resolve_active_actor(actor)
        self.assertIsNotNone(marked)
        actor.groups.clear()
        self.assertNotIn(issue, list(review_issue_queryset(marked)))

    def test_mixed_queryset_preserves_source_rows_when_object_rows_are_filtered(self):
        actor = self.review_operator("mixed-query-operator")
        public_source = self.create_source(
            code="mixed-query-source",
            scope_rule="authenticated_user",
            config={},
        )
        source_issue = MemoryIngestionIssue.objects.create(
            source=public_source,
            issue_kind=MemoryIngestionIssue.IssueKind.INDEX_FAILED,
            severity=MemoryIngestionIssue.Severity.ERROR,
            message="source row",
        )
        queryset = review_issue_queryset(actor)
        self.assertIn(source_issue, list(queryset))

    def test_duplicate_object_ids_are_scoped_by_source_code(self):
        actor = self.review_operator("duplicate-object-operator")
        visible_source = self.create_source(code="duplicate-visible", scope_rule="authenticated_user", config={})
        hidden_source = self.create_source(
            code="duplicate-hidden",
            scope_rule="manual_scope_mapping",
            config={"scope_tokens": ["group:other"]},
        )
        visible = MemorySourceObject.objects.create(
            source=visible_source,
            object_id="same-object-id",
            object_uri="source://visible",
            relative_path="visible.txt",
            file_name="visible.txt",
            metadata={"scope_tokens": ["org:default"]},
        )
        MemorySourceObject.objects.create(
            source=hidden_source,
            object_id="same-object-id",
            object_uri="source://hidden",
            relative_path="hidden.txt",
            file_name="hidden.txt",
            metadata={"scope_tokens": ["group:other"]},
        )
        foreign_job = MemoryExternalConnectorJob.objects.create(
            source_code=hidden_source.code,
            job_kind=MemoryQueueJobKind.REINDEX,
            status="pending",
            idempotency_key="duplicate-object-foreign-job",
            payload={"source_object_id": visible.object_id},
        )
        self.assertNotIn(foreign_job, list(_scoped_index_job_queryset(actor)))

    def test_pending_accept_checks_current_and_proposed_frontmatter_scope(self):
        actor = self.review_operator("pending-scope-operator")
        role, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
        actor.groups.add(role)
        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            item = MemoryKnowledgeItem.objects.create(
                memory_id="pending-scope-boundary",
                scope=MemoryKnowledgeItem.Scope.ORGANIZATION,
                created_by=actor,
                kind=MemoryKnowledgeItem.Kind.FACT,
                text_hash="pending-scope-text",
                scope_tokens=["org:default"],
                metadata={"lifecycle": "pending"},
            )
            result = write_knowledge_item_file(item, body="pending scope text")
            proposed = result.absolute_path.read_text(encoding="utf-8").replace("org:default", "group:hidden")
            result.absolute_path.write_text(proposed, encoding="utf-8")

            with self.assertRaises(PermissionDenied):
                accept_pending_item(item=item, actor=actor)

    def test_assignee_must_be_active_operator_with_target_access(self):
        actor = self.review_operator("assignee-actor")
        source = self.create_source(code="assignee-boundary")
        source_object = MemorySourceObject.objects.create(
            source=source,
            object_id="assignee-target",
            object_uri="source://assignee-target",
            relative_path="target.txt",
            file_name="target.txt",
            metadata={"scope_tokens": ["org:default"]},
        )
        issue = MemoryIngestionIssue.objects.create(
            source=source,
            source_object=source_object,
            issue_kind=MemoryIngestionIssue.IssueKind.INDEX_FAILED,
            severity=MemoryIngestionIssue.Severity.ERROR,
            message="assignee target",
        )
        inactive = self.review_operator("inactive-assignee")
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])
        plain = User.objects.create_user(username="plain-assignee", password="pass")

        with self.assertRaises(ValidationError):
            apply_issue_review_action(actor=actor, issue=issue, action="assign", payload={"assigned_to": inactive.pk})
        with self.assertRaises(ValidationError):
            apply_issue_review_action(actor=actor, issue=issue, action="assign", payload={"assigned_to": plain.pk})

    def test_assignees_selector_excludes_foreign_scope_operator(self):
        actor = self.review_operator("assignee-selector-actor")
        allowed_group, _ = Group.objects.get_or_create(name="allowed-review-scope")
        actor.groups.add(allowed_group)
        foreign = self.review_operator("foreign-scope-assignee")
        source = self.create_source(code="assignee-selector-source")
        source_object = MemorySourceObject.objects.create(
            source=source,
            object_id="assignee-selector-target",
            object_uri="source://assignee-selector-target",
            relative_path="target.txt",
            file_name="target.txt",
            metadata={"scope_tokens": ["group:allowed-review-scope"]},
        )
        issue = MemoryIngestionIssue.objects.create(
            source=source,
            source_object=source_object,
            issue_kind=MemoryIngestionIssue.IssueKind.INDEX_FAILED,
            severity=MemoryIngestionIssue.Severity.ERROR,
            message="selector scope",
        )
        assignees = assignees_for_issue(issue, actor=actor)
        self.assertIn(actor, assignees)
        self.assertNotIn(foreign, assignees)

    def test_render_requires_actor_and_digest_requires_explicit_actor_or_scope(self):
        source = self.create_source(code="render-boundary")
        source_object = MemorySourceObject.objects.create(
            source=source,
            object_id="render-target",
            object_uri="source://render-target",
            relative_path="render.txt",
            file_name="render.txt",
            metadata={"safe_text": "sensitive cached text", "scope_tokens": ["org:default"]},
        )
        from apps.memory.services import compile_knowledge_item_digest, render_source_object_text

        self.assertEqual(render_source_object_text(source_object), "")
        with self.assertRaises(PermissionDenied):
            compile_knowledge_item_digest()

    def test_source_object_access_refreshes_stale_superuser_demotion(self):
        root = User.objects.create_superuser(username="stale-root", password="pass")
        source = self.create_source(
            code="stale-root-source",
            scope_rule="manual_scope_mapping",
            config={"scope_tokens": ["group:restricted"]},
        )
        source_object = MemorySourceObject.objects.create(
            source=source,
            object_id="stale-root-target",
            object_uri="source://stale-root-target",
            relative_path="target.txt",
            file_name="target.txt",
            metadata={"scope_tokens": ["group:restricted"]},
        )
        self.assertTrue(can_access_source_object(root, source_object))
        root.is_superuser = False
        root.save(update_fields=["is_superuser"])
        self.assertFalse(can_access_source_object(root, source_object))

    def test_search_document_text_requires_fresh_actor_and_never_returns_foreign_metadata(self):
        from apps.memory.retrieval import read_search_document_text

        actor = self.review_operator("direct-read-actor")
        source = self.create_source(
            code="direct-read-source",
            scope_rule="manual_scope_mapping",
            config={"scope_tokens": ["group:foreign"]},
        )
        source_object = MemorySourceObject.objects.create(
            source=source,
            object_id="foreign-text",
            object_uri="source://foreign-text",
            relative_path="private/foreign.txt",
            file_name="foreign.txt",
            metadata={"scope_tokens": ["group:foreign"], "safe_text": "foreign secret"},
        )
        document = MemorySearchDocument.objects.create(
            document_id="source:foreign-text",
            corpus_type=MemorySearchDocument.CorpusType.SOURCE_DATA,
            object_kind=MemorySearchDocument.ObjectKind.SOURCE_OBJECT,
            source_object=source_object,
            index_status=MemorySearchDocument.IndexStatus.READY,
        )
        with self.assertRaises(PermissionDenied):
            read_search_document_text(document, actor=None)
        with self.assertRaises(PermissionDenied):
            read_search_document_text(document, actor=actor)

    def test_unresolved_acl_is_fail_closed_unless_explicit_fallback_is_enabled(self):
        actor = self.review_operator("unresolved-acl-actor")
        source = self.create_source(code="unresolved-acl-source", scope_rule="authenticated_user")
        source_object = MemorySourceObject.objects.create(
            source=source,
            object_id="unresolved-acl-target",
            object_uri="source://unresolved-acl-target",
            relative_path="unresolved.txt",
            file_name="unresolved.txt",
            metadata={
                "scope_tokens": ["org:default"],
                "acl": {"status": "unresolved", "scope_tokens": ["org:default"]},
            },
        )
        with self.settings(MEMORY_ACL_UNRESOLVED_POLICY="block"):
            self.assertEqual(source_object_scope_tokens(source_object), [])
            self.assertFalse(can_access_source_object(actor, source_object))
        source_object.metadata["acl"]["unresolved_policy"] = "fallback_scope_rule"
        source_object.save(update_fields=["metadata", "updated_at"])
        self.assertEqual(source_object_scope_tokens(source_object), ["org:default"])
        self.assertTrue(can_access_source_object(actor, source_object))

    def test_actor_bound_git_feed_drops_mixed_foreign_personal_commit(self):
        from apps.memory.knowledge_files import recent_knowledge_commits_for_actor

        actor = self.review_operator("git-feed-actor")
        entries = [
            {"hash": "own", "date": "2026-01-03", "author": "a", "subject": "own", "paths": (f"users/{actor.pk}/a.md",)},
            {
                "hash": "mixed",
                "date": "2026-01-02",
                "author": "a",
                "subject": "mixed",
                "paths": (f"users/{actor.pk}/a.md", "users/999/secret.md"),
            },
        ]
        with TemporaryDirectory() as tmpdir, patch("apps.memory.knowledge_files.knowledge_repo_root", return_value=Path(tmpdir)), patch(
            "apps.memory.knowledge_files._git_log_entries_with_paths", return_value=entries
        ):
            Path(tmpdir, ".git").mkdir()
            commits = recent_knowledge_commits_for_actor(actor=actor)
        self.assertEqual([entry["hash"] for entry in commits], ["own"])

    def test_actor_bound_git_feed_parses_real_name_only_history(self):
        from apps.memory.knowledge_files import recent_knowledge_commits_for_actor

        actor = self.review_operator("real-git-feed-actor")
        with TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"LOCAL_BUSINESS_KNOWLEDGE_REPO_DIR": tmpdir}):
            def git(*args):
                return subprocess.run(
                    ["git", *args],
                    cwd=tmpdir,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )

            git("init", "-q")
            git("config", "user.email", "memory@example.test")
            git("config", "user.name", "Memory Test")
            own_path = Path(tmpdir) / "users" / str(actor.pk) / "own.md"
            own_path.parent.mkdir(parents=True)
            own_path.write_text("own", encoding="utf-8")
            git("add", ".")
            git("commit", "-q", "-m", "own commit")

            foreign_path = Path(tmpdir) / "users" / "999" / "foreign.md"
            foreign_path.parent.mkdir(parents=True)
            foreign_path.write_text("foreign", encoding="utf-8")
            own_path.write_text("own changed", encoding="utf-8")
            git("add", ".")
            git("commit", "-q", "-m", "mixed commit")

            commits = recent_knowledge_commits_for_actor(actor=actor, limit=10)

        subjects = [entry["subject"] for entry in commits]
        self.assertIn("own commit", subjects)
        self.assertNotIn("mixed commit", subjects)

    def test_direct_review_contexts_and_mismatched_issue_fail_closed(self):
        actor = self.review_operator("hidden-context-actor")
        foreign_source = self.create_source(
            code="hidden-context-source",
            scope_rule="manual_scope_mapping",
            config={"scope_tokens": ["group:foreign"]},
        )
        source_object = MemorySourceObject.objects.create(
            source=foreign_source,
            object_id="hidden-context-target",
            object_uri="source://hidden-context-target",
            relative_path="hidden.txt",
            file_name="hidden.txt",
            metadata={"scope_tokens": ["group:foreign"]},
        )
        issue = MemoryIngestionIssue.objects.create(
            source=foreign_source,
            source_object=source_object,
            issue_kind=MemoryIngestionIssue.IssueKind.INDEX_FAILED,
            severity=MemoryIngestionIssue.Severity.ERROR,
            message="foreign context",
        )
        document = MemorySearchDocument.objects.create(
            document_id="hidden-context-document",
            corpus_type=MemorySearchDocument.CorpusType.SOURCE_DATA,
            object_kind=MemorySearchDocument.ObjectKind.SOURCE_OBJECT,
            source_object=source_object,
            index_status=MemorySearchDocument.IndexStatus.READY,
        )
        with self.assertRaises(PermissionDenied):
            issue_to_review_queue_item(issue, user=actor)
        with self.assertRaises(PermissionDenied):
            issue_detail_context(issue, user=actor)
        with self.assertRaises(PermissionDenied):
            search_document_detail_context(document, user=actor)

        other_source = self.create_source(code="mismatched-issue-source")
        mismatched = MemoryIngestionIssue.objects.create(
            source=other_source,
            source_object=source_object,
            issue_kind=MemoryIngestionIssue.IssueKind.INDEX_FAILED,
            severity=MemoryIngestionIssue.Severity.ERROR,
            message="mismatched source",
        )
        with self.assertRaises(PermissionDenied):
            apply_issue_review_action(actor=actor, issue=mismatched, action="acknowledge")
