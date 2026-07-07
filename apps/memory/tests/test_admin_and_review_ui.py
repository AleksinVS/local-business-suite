"""Тесты Django Admin наблюдаемости и UI ревью памяти."""
from apps.memory.tests._common import *  # noqa: F401,F403


class MemoryAdminObservabilityTests(TestCase):
    databases = RUNTIME_DATABASES
    def test_memory_admin_registers_observability_models(self):
        expected_admin_classes = {
            MemorySource: MemorySourceAdmin,
            MemorySearchDocument: MemorySearchDocumentAdmin,
            MemoryExternalConnectorJob: django_admin.site._registry[MemoryExternalConnectorJob].__class__,
            MemoryAccessAudit: MemoryAccessAuditAdmin,
            MemoryEvalCase: MemoryEvalCaseAdmin,
            MemorySourceObject: django_admin.site._registry[MemorySourceObject].__class__,
            MemoryIngestionRun: django_admin.site._registry[MemoryIngestionRun].__class__,
            MemoryIngestionIssue: django_admin.site._registry[MemoryIngestionIssue].__class__,
            MemoryKnowledgeEdge: django_admin.site._registry[MemoryKnowledgeEdge].__class__,
            MemoryKnowledgeItem: MemoryKnowledgeItemAdmin,
            SecretHandle: django_admin.site._registry[SecretHandle].__class__,
            SecretAccessAudit: django_admin.site._registry[SecretAccessAudit].__class__,
        }

        for model, admin_class in expected_admin_classes.items():
            with self.subTest(model=model.__name__):
                self.assertIsInstance(django_admin.site._registry[model], admin_class)

    def test_memory_candidate_and_review_action_tables_are_gone_from_schema(self):
        """ADR-0030 decision 4: MemoryKnowledgeCandidate/MemoryReviewAction are
        removed outright, not just deprecated; candidacy and issue/index
        review now ride pending pages + the issue queue + git history."""
        from django.db import connection

        self.assertIsNone(get_optional_memory_model("MemoryKnowledgeCandidate"))
        self.assertIsNone(get_optional_memory_model("MemoryReviewAction"))
        table_names = set(connection.introspection.table_names())
        self.assertNotIn("memory_memoryknowledgecandidate", table_names)
        self.assertNotIn("memory_memoryreviewaction", table_names)

    def test_memory_graph_extraction_contour_is_gone_from_schema_and_code(self):
        """ADR-0030 decision 3: the LLM graph-extraction contour (entities,
        extraction runs, schema proposals, review items) is removed outright;
        typed edges now come from the deterministic ``relations:``
        materializer (``MemoryKnowledgeEdge``), not an LLM extraction run."""
        from django.db import connection

        for model_name in (
            "MemoryGraphEntity",
            "MemoryGraphExtractionRun",
            "MemoryGraphSchemaProposal",
            "MemoryGraphReviewItem",
        ):
            self.assertIsNone(get_optional_memory_model(model_name))
        table_names = set(connection.introspection.table_names())
        for table_name in (
            "memory_memorygraphentity",
            "memory_memorygraphextractionrun",
            "memory_memorygraphschemaproposal",
            "memory_memorygraphreviewitem",
        ):
            self.assertNotIn(table_name, table_names)
        available_commands = get_commands()
        self.assertNotIn("memory_graph_extract", available_commands)
        self.assertNotIn("memory_graph_schema_discover", available_commands)

    def test_memory_admin_search_fields_do_not_include_storage_paths(self):
        path_fields = {"raw_path", "safe_path", "text_path"}

        for model in (
            MemorySource,
            MemorySearchDocument,
            MemoryExternalConnectorJob,
            MemoryAccessAudit,
            MemoryEvalCase,
            MemorySourceObject,
            MemoryIngestionRun,
            MemoryIngestionIssue,
            MemoryKnowledgeEdge,
            MemoryKnowledgeItem,
            SecretHandle,
            SecretAccessAudit,
        ):
            with self.subTest(model=model.__name__):
                model_admin = django_admin.site._registry[model]
                self.assertTrue(path_fields.isdisjoint(model_admin.search_fields))


class MemoryReviewUITests(MemoryModelFactoryMixin, TestCase):
    databases = RUNTIME_DATABASES

    def create_review_user(self, username="memory-reviewer", group_name="memory_admin"):
        user = User.objects.create_user(username=username, password="pass")
        group, _created = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)
        return user

    def create_review_issue(
        self,
        *,
        issue_kind=MemoryIngestionIssue.IssueKind.PII_AUDIT,
        message=None,
        source_code="review_source",
        document_id="source:review-doc-1",
        scope_tokens=None,
    ):
        source = self.create_source(code=source_code, sensitivity="confidential")
        document = self.create_search_document(
            source=source,
            document_id=document_id,
            scope_tokens=scope_tokens or ["org:default"],
            metadata={
                "index_versions": {"fulltext": "sqlite-fts-v1"},
                "content_hash": "text-hash-1",
                "pii_probe": "audit-person@example.com",
            },
        )
        issue = MemoryIngestionIssue.objects.create(
            source=source,
            source_object=document.source_object,
            issue_kind=issue_kind,
            severity=MemoryIngestionIssue.Severity.WARNING,
            message=message or "PII audit required for audit-person@example.com.",
            metadata={"detector": "test", "sample": "audit-person@example.com"},
        )
        return source, document, issue

    def test_review_ui_requires_review_permission(self):
        user = User.objects.create_user(username="plain-user", password="pass")
        self.client.force_login(user)

        response = self.client.get(reverse("memory:review_dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_review_queue_uses_projection_without_persistent_review_case(self):
        user = self.create_review_user()
        _source, _document, issue = self.create_review_issue()

        item = issue_to_review_queue_item(issue, user=user)

        self.assertIsNone(get_optional_memory_model("MemoryReviewCase"))
        self.assertEqual(item.source_model, "MemoryIngestionIssue")
        self.assertEqual(item.stable_key, f"issue:{issue.pk}")
        self.assertNotIn("audit-person@example.com", item.safe_summary)

    def test_issue_detail_resolve_writes_safe_review_action(self):
        """ADR-0030 decision 4: the removed MemoryReviewAction table's role is
        folded into the issue itself: the resolution is a direct field
        mutation, and a bounded safe-redacted ``review_log`` entry lives in
        ``issue.metadata`` (no separate action-log row/table)."""
        user = self.create_review_user()
        _source, _document, issue = self.create_review_issue()
        self.client.force_login(user)

        detail_response = self.client.get(reverse("memory:review_issue_detail", kwargs={"pk": issue.pk}))
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "PII audit")
        self.assertNotContains(detail_response, "audit-person@example.com")

        response = self.client.post(
            reverse("memory:review_issue_action", kwargs={"pk": issue.pk}),
            {
                "action": "resolve",
                "resolution_code": "audit_accepted",
                "comment": "Проверено: audit-person@example.com password=supersecretvalue",
            },
        )

        self.assertEqual(response.status_code, 302)
        issue.refresh_from_db()
        self.assertEqual(issue.status, MemoryIngestionIssue.Status.RESOLVED)
        review_log = issue.metadata.get("review_log") or []
        self.assertEqual(review_log[-1]["action"], "resolve")
        action_payload = json.dumps(review_log, ensure_ascii=False)
        self.assertNotIn("audit-person@example.com", action_payload)
        self.assertNotIn("supersecretvalue", action_payload)
        detail_response_2 = self.client.get(reverse("memory:review_issue_detail", kwargs={"pk": issue.pk}))
        self.assertNotContains(detail_response_2, "audit-person@example.com")
        self.assertNotContains(detail_response_2, "supersecretvalue")

    def test_index_health_enqueue_and_delete_stale_actions(self):
        user = self.create_review_user()
        _source, document, _issue = self.create_review_issue()
        self.client.force_login(user)

        list_response = self.client.get(reverse("memory:review_index_list"), {"gap": "missing_vector"})
        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, document.document_id)

        enqueue_response = self.client.post(
            reverse("memory:review_index_action", kwargs={"document_id": document.document_id}),
            {"action": "enqueue_reindex"},
        )
        self.assertEqual(enqueue_response.status_code, 302)
        job = MemoryExternalConnectorJob.objects.get(payload__document_id=document.document_id)
        self.assertEqual(job.job_kind, MemoryQueueJobKind.REINDEX)
        dashboard_response = self.client.get(reverse("memory:review_dashboard"))
        detail_response = self.client.get(reverse("memory:review_index_detail", kwargs={"document_id": document.document_id}))
        self.assertContains(dashboard_response, "reindex")
        self.assertContains(dashboard_response, "pending")
        self.assertContains(detail_response, "reindex")
        self.assertContains(detail_response, "pending")
        document.refresh_from_db()
        enqueue_log = document.metadata.get("review_log") or []
        self.assertEqual(enqueue_log[-1]["action"], "enqueue_reindex")
        self.assertEqual(enqueue_log[-1]["decision"], "queued")

        with patch("apps.memory.review_services.delete_search_document_indexes", return_value={"fulltext_deleted": 1, "vector_deleted": 1}):
            delete_response = self.client.post(
                reverse("memory:review_index_action", kwargs={"document_id": document.document_id}),
                {"action": "delete_stale_index"},
            )
        self.assertEqual(delete_response.status_code, 302)
        document.refresh_from_db()
        self.assertEqual(document.index_status, MemorySearchDocument.IndexStatus.DELETED)
        delete_log = document.metadata.get("review_log") or []
        self.assertEqual(delete_log[-1]["action"], "delete_stale_index")

    def test_review_queue_and_index_pages_filter_by_scope_tokens(self):
        user = self.create_review_user()
        _source, visible_document, visible_issue = self.create_review_issue()
        _hidden_source, hidden_document, hidden_issue = self.create_review_issue(
            source_code="hidden_source",
            document_id="source:hidden-doc-1",
            scope_tokens=["role:hidden-reviewers"],
        )
        self.client.force_login(user)

        self.assertIn(visible_issue, list(review_issue_queryset(user)))
        self.assertNotIn(hidden_issue, list(review_issue_queryset(user)))
        self.assertIn(visible_document, list(index_document_queryset(user)))
        self.assertNotIn(hidden_document, list(index_document_queryset(user)))

        dashboard_response = self.client.get(reverse("memory:review_dashboard"))
        hidden_issue_response = self.client.get(reverse("memory:review_issue_detail", kwargs={"pk": hidden_issue.pk}))
        hidden_document_response = self.client.get(
            reverse("memory:review_index_detail", kwargs={"document_id": hidden_document.document_id})
        )

        self.assertEqual(dashboard_response.status_code, 200)
        self.assertEqual(hidden_issue_response.status_code, 404)
        self.assertEqual(hidden_document_response.status_code, 404)

    def test_hidden_index_document_cannot_be_mutated_by_direct_post(self):
        user = self.create_review_user()
        _source, hidden_document, _issue = self.create_review_issue(
            source_code="hidden_post_source",
            document_id="source:hidden-post-doc-1",
            scope_tokens=["role:hidden-reviewers"],
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("memory:review_index_action", kwargs={"document_id": hidden_document.document_id}),
            {"action": "enqueue_reindex"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(MemoryExternalConnectorJob.objects.filter(payload__document_id=hidden_document.document_id).exists())

    def test_delete_stale_index_rejects_healthy_document(self):
        user = self.create_review_user()
        source = self.create_source(code="healthy_index_source", sensitivity="confidential")
        document = self.create_search_document(
            source=source,
            document_id="source:healthy-index-doc-1",
            metadata={
                "index_versions": {"fulltext": "sqlite-fts-v1", "vector": "sqlite-vector-v1"},
                "content_hash": "text-hash-1",
            },
        )

        with self.assertRaises(ValidationError):
            apply_index_review_action(
                actor=user,
                document=document,
                action="delete_stale_index",
            )

        document.refresh_from_db()
        self.assertEqual(document.index_status, MemorySearchDocument.IndexStatus.READY)

    def test_index_operator_can_enqueue_issue_reindex_without_issue_review_permission(self):
        user = self.create_review_user(username="index-operator", group_name="memory_index_operator")
        _source, document, issue = self.create_review_issue(issue_kind=MemoryIngestionIssue.IssueKind.INDEX_FAILED)

        outcome = apply_issue_review_action(
            actor=user,
            issue=issue,
            action="enqueue_reindex",
        )

        self.assertEqual(outcome.decision, "queued")
        self.assertTrue(MemoryExternalConnectorJob.objects.filter(payload__document_id=document.document_id).exists())

    def test_index_queryset_without_gap_remains_lazy(self):
        user = self.create_review_user()
        self.create_review_issue()

        documents = index_document_queryset(user)

        self.assertNotIsInstance(documents, list)


class MemoryPendingReviewUITests(MemoryModelFactoryMixin, TestCase):
    """Review UI over the git propose -> pending -> review -> stable
    primitive (ADR-0030 decisions 4 & 8), replacing MemoryKnowledgeCandidate."""

    databases = RUNTIME_DATABASES

    def create_review_user(self, username="pending-reviewer", group_name="memory_admin"):
        user = User.objects.create_user(username=username, password="pass")
        group, _created = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)
        return user

    def _make_candidate(self, tmpdir):
        from apps.ai.models import ChatMessage, ChatSession

        from ..chat_memory import propose_reflection_candidates, remember_knowledge

        user = User.objects.create_user(username="pending-personal-user", password="pass")
        session = ChatSession.objects.create(user=user, title="Memory chat")
        message = ChatMessage.objects.create(
            session=session, role=ChatMessage.Role.USER, content="Запомни: общий регламент gamma для отдела."
        )
        remember_knowledge(
            actor=user,
            session=session,
            payload={"message_ids": [message.id], "importance": "organization_candidate"},
            request_id="req-pending-ui-candidate",
        )
        return propose_reflection_candidates()[0]

    def test_pending_list_requires_review_permission(self):
        plain_user = User.objects.create_user(username="pending-plain-user", password="pass")
        self.client.force_login(plain_user)

        response = self.client.get(reverse("memory:review_pending_list"))

        self.assertEqual(response.status_code, 403)

    def test_pending_list_shows_candidate_and_accept_flips_lifecycle(self):
        reviewer = self.create_review_user()
        reviewer.is_superuser = True
        reviewer.save(update_fields=["is_superuser"])
        self.client.force_login(reviewer)

        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            candidate = self._make_candidate(tmpdir)

            list_response = self.client.get(reverse("memory:review_pending_list"))
            self.assertEqual(list_response.status_code, 200)
            self.assertContains(list_response, candidate.memory_id)

            accept_response = self.client.post(
                reverse("memory:review_pending_action", kwargs={"memory_id": candidate.memory_id}),
                {"action": "accept"},
            )
            self.assertEqual(accept_response.status_code, 302)
            candidate.refresh_from_db()
            self.assertEqual(candidate.metadata.get("lifecycle"), "current")

            list_response_after = self.client.get(reverse("memory:review_pending_list"))
            self.assertNotContains(list_response_after, candidate.memory_id)

    def test_pending_action_requires_organization_review_permission(self):
        reviewer = self.create_review_user(username="pending-reviewer-no-org-perm")
        self.client.force_login(reviewer)

        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            candidate = self._make_candidate(tmpdir)

            response = self.client.post(
                reverse("memory:review_pending_action", kwargs={"memory_id": candidate.memory_id}),
                {"action": "accept"},
            )

            self.assertEqual(response.status_code, 302)
            candidate.refresh_from_db()
            self.assertEqual(candidate.metadata.get("lifecycle"), "pending")
