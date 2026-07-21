"""Тесты chat knowledge (remember/reflection/pending)."""
from apps.memory.tests._common import *  # noqa: F401,F403


class MemoryChatKnowledgeTests(TestCase):
    databases = RUNTIME_DATABASES
    def create_chat(self, *, username="chat-memory-user", text="Запомни: насос alpha требует калибровку."):
        from apps.ai.models import ChatMessage, ChatSession

        user = User.objects.create_user(username=username, password="pass")
        session = ChatSession.objects.create(user=user, title="Memory chat")
        message = ChatMessage.objects.create(session=session, role=ChatMessage.Role.USER, content=text)
        return user, session, message

    def test_chat_delete_nullifies_knowledge_item_session(self):
        """Deleting a ChatSession must set source_session_id=NULL on any
        MemoryKnowledgeItem rows that referenced it (standard Django
        on_delete=SET_NULL, now that chat and memory tables live in one
        database); the knowledge item and its file survive the chat delete."""
        from ..chat_memory import remember_knowledge

        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            user, session, message = self.create_chat()
            result = remember_knowledge(
                actor=user,
                session=session,
                payload={"message_ids": [message.id], "user_note": "x"},
                request_id="req-delete-chat-1",
            )
            item = MemoryKnowledgeItem.objects.get(memory_id=result["memory_id"])
            self.assertEqual(item.source_session_id, session.id)

            session.delete()

            item.refresh_from_db()
            self.assertIsNone(item.source_session_id)
            # Row itself survives — the knowledge item is independent of the chat.
            self.assertEqual(MemoryKnowledgeItem.objects.filter(memory_id=result["memory_id"]).count(), 1)

    def test_remember_knowledge_writes_personal_memory_synchronously(self):
        """memory.remember is a single synchronous call (ADR-0030 decision 2):
        one call creates the file, the git commit, and the search index; there
        is no MemoryWriteRequest/MemoryIndexJob queue status in the result."""
        from ..chat_memory import remember_knowledge
        from ..retrieval import memory_search

        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            user, session, message = self.create_chat()
            other_user = User.objects.create_user(username="chat-memory-other-user", password="pass")
            result = remember_knowledge(
                actor=user,
                session=session,
                payload={"message_ids": [message.id], "user_note": "важно"},
                request_id="req-remember-1",
            )

            self.assertEqual(session._state.db, "default")
            self.assertNotIn("request_id", result)
            self.assertNotIn("job_id", result)
            self.assertNotIn("event_id", result)
            self.assertEqual(result["target_scope"], "personal")
            self.assertEqual(result["index_status"], "ready")
            self.assertTrue(result["knowledge_file_commit"])

            item = MemoryKnowledgeItem.objects.get(memory_id=result["memory_id"])
            self.assertEqual(item.owner_user, user)
            self.assertEqual(item.scope, MemoryKnowledgeItem.Scope.PERSONAL)
            self.assertEqual(item.knowledge_file_path, result["knowledge_file_path"])
            self.assertTrue((Path(tmpdir) / "knowledge_repo" / "users" / str(user.id) / "index.md").exists())
            self.assertFalse((Path(tmpdir) / "knowledge_repo" / "users" / str(user.id) / "_summary.md").exists())
            self.assertTrue((Path(tmpdir) / "knowledge_repo" / ".git").exists())
            self.assertIsNone(get_optional_memory_model("MemoryClaim"))
            self.assertIsNone(get_optional_memory_model("MemoryBelief"))

            found = memory_search(
                actor=user,
                query="насос alpha калибровку",
                sensitivity="internal",
                request_id="req-remember-search",
            )
            self.assertEqual(found["items"][0]["kind"], "knowledge")
            self.assertEqual(found["items"][0]["result_type"], "knowledge")
            self.assertIn("насос alpha требует калибровку", found["items"][0]["text"])

            denied = memory_search(
                actor=other_user,
                query="насос alpha калибровку",
                sensitivity="internal",
                request_id="req-remember-search-denied",
            )
            self.assertEqual(denied["items"], [])

    def test_remember_knowledge_indexing_failure_enqueues_retryable_reindex_task(self):
        """If inline indexing raises, the write must still succeed (file +
        commit + memory_id); a retryable reindex task lands on the unified
        queue and eventually reaches dead_letter once retries are exhausted."""
        from ..chat_memory import remember_knowledge

        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            user, session, message = self.create_chat()
            with patch("apps.memory.chat_memory.index_knowledge_item", side_effect=RuntimeError("backend unavailable")):
                result = remember_knowledge(
                    actor=user,
                    session=session,
                    payload={"message_ids": [message.id]},
                    request_id="req-remember-index-fail",
                )

            self.assertTrue(result["memory_id"])
            self.assertTrue(result["knowledge_file_commit"])
            self.assertEqual(result["index_status"], "indexing_pending")

            job = MemoryExternalConnectorJob.objects.get(idempotency_key=f"reindex:{result['memory_id']}")
            self.assertEqual(job.job_kind, MemoryQueueJobKind.REINDEX)
            self.assertEqual(job.status, "pending")
            self.assertEqual(job.max_attempts, 3)

            for _ in range(job.max_attempts):
                leased = lease_memory_queue_tasks(job_kinds=[MemoryQueueJobKind.REINDEX], limit=1)
                self.assertEqual(len(leased), 1)
                fail_memory_queue_task(leased[0].job_id, error_message="backend unavailable")
                job.refresh_from_db()
                if job.status != "dead_letter":
                    job.next_attempt_at = timezone.now() - timedelta(seconds=1)
                    job.save(update_fields=["next_attempt_at"])

            job.refresh_from_db()
            self.assertEqual(job.status, "dead_letter")
            self.assertEqual(job.attempt_count, job.max_attempts)

    def test_secret_span_becomes_handle_and_non_secret_text_is_indexed(self):
        from ..chat_memory import remember_knowledge
        from ..retrieval import memory_search

        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir), LOCAL_BUSINESS_SECRET_VAULT_BASE_URL="https://vault.example"):
            secret_value = "not-a-real-secret-value"
            user, session, message = self.create_chat(
                text=f"Запомни: тестовый стенд называется alpha. Пароль: {secret_value}"
            )
            result = remember_knowledge(
                actor=user,
                session=session,
                payload={"message_ids": [message.id]},
                request_id="req-secret-memory",
            )
            item = MemoryKnowledgeItem.objects.get(memory_id=result["memory_id"])
            saved_text = read_knowledge_item_file(item).body

            self.assertIn("тестовый стенд называется alpha", saved_text)
            self.assertIn("<SECRET_HANDLE:secret:", saved_text)
            self.assertNotIn(secret_value, saved_text)
            self.assertEqual(SecretHandle.objects.count(), 1)
            self.assertEqual(SecretAccessAudit.objects.count(), 1)
            self.assertTrue(result["secret_handles"])
            self.assertNotIn(secret_value, json.dumps(result, ensure_ascii=False))

            found = memory_search(
                actor=user,
                query="тестовый стенд alpha",
                sensitivity="confidential",
                request_id="req-secret-memory-search",
            )
            self.assertEqual(len(found["items"]), 1)
            self.assertNotIn(secret_value, json.dumps(found, ensure_ascii=False))

            if settings.LOCAL_BUSINESS_MEMORY_FULLTEXT_BACKEND == "sqlite_fts":
                index_path = Path(tmpdir) / "indexes" / "fulltext" / "search.sqlite3"
                self.assertTrue(index_path.exists())
                self.assertNotIn(secret_value.encode("utf-8"), index_path.read_bytes())
            else:
                from ..models import MemoryFullTextIndex

                rows = list(MemoryFullTextIndex.objects.filter(is_active=True))
                self.assertTrue(rows)
                for row in rows:
                    self.assertNotIn(secret_value, row.search_text)

    def test_organization_memory_requires_staff_permission(self):
        from django.core.exceptions import PermissionDenied

        from ..chat_memory import remember_knowledge

        user, session, message = self.create_chat(username="org-denied-user")

        with self.assertRaises(PermissionDenied):
            remember_knowledge(
                actor=user,
                session=session,
                payload={"message_ids": [message.id], "target_scope": "organization"},
                request_id="req-org-denied",
            )

    def test_reflection_creates_organization_candidate_for_high_importance_personal_memory(self):
        """ADR-0030 decisions 4 & 8: personal->organization candidacy rides
        the git propose -> pending -> review -> stable primitive. The
        candidate is a pending org page that normal search cannot find until
        a knowledge owner accepts it; a rejected candidate is never found and
        the decision is recorded as a git commit."""
        from ..chat_memory import propose_reflection_candidates, remember_knowledge
        from ..retrieval import memory_search
        from ..review_services import accept_pending_item

        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            user, session, message = self.create_chat(text="Запомни: общий регламент alpha действует для отдела.")
            remember_knowledge(
                actor=user,
                session=session,
                payload={"message_ids": [message.id], "importance": "organization_candidate"},
                request_id="req-candidate",
            )

            candidates = propose_reflection_candidates()

            self.assertEqual(len(candidates), 1)
            candidate = candidates[0]
            self.assertEqual(candidate.scope, MemoryKnowledgeItem.Scope.ORGANIZATION)
            self.assertEqual(candidate.metadata.get("lifecycle"), "pending")
            self.assertIn(candidate, list(pending_knowledge_queryset(self.superuser())))

            # A second reflection pass must not create a duplicate proposal.
            self.assertEqual(len(propose_reflection_candidates()), 0)

            org_reader = User.objects.create_user(username="org-candidate-reader", password="pass")
            not_found = memory_search(
                actor=org_reader,
                query="общий регламент alpha отдела",
                scope_tokens=["org:default"],
                sensitivity="internal",
                request_id="req-candidate-pending-search",
            )
            self.assertEqual(not_found["items"], [])

            reviewer = self.superuser()
            accepted = accept_pending_item(item=candidate, actor=reviewer)
            self.assertEqual(accepted.metadata.get("lifecycle"), "current")

            found = memory_search(
                actor=org_reader,
                query="общий регламент alpha отдела",
                scope_tokens=["org:default"],
                sensitivity="internal",
                request_id="req-candidate-accepted-search",
            )
            self.assertEqual(len(found["items"]), 1)
            self.assertTrue(accepted.knowledge_file_path.startswith("org/"))

    def test_rejected_organization_candidate_is_never_searchable_and_recorded_in_git(self):
        from ..chat_memory import propose_reflection_candidates, remember_knowledge
        from ..knowledge_files import _run_git_optional, knowledge_repo_root
        from ..retrieval import memory_search
        from ..review_services import reject_pending_item

        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            user, session, message = self.create_chat(text="Запомни: черновой регламент beta для отдела.")
            remember_knowledge(
                actor=user,
                session=session,
                payload={"message_ids": [message.id], "importance": "organization_candidate"},
                request_id="req-candidate-reject",
            )
            candidate = propose_reflection_candidates()[0]

            rejected = reject_pending_item(item=candidate, actor=self.superuser(), reason="Не соответствует регламенту.")

            self.assertEqual(rejected.status, MemoryKnowledgeItem.Status.DELETED)
            self.assertEqual(rejected.metadata.get("lifecycle"), "rejected")
            self.assertNotIn(rejected, list(pending_knowledge_queryset(self.superuser())))

            org_reader = User.objects.create_user(username="org-candidate-reject-reader", password="pass")
            not_found = memory_search(
                actor=org_reader,
                query="черновой регламент beta отдела",
                scope_tokens=["org:default"],
                sensitivity="internal",
                request_id="req-candidate-rejected-search",
            )
            self.assertEqual(not_found["items"], [])

            log_output = _run_git_optional(knowledge_repo_root(), "log", "--oneline").stdout
            self.assertIn("Reject organization candidate", log_output)

    def superuser(self):
        return User.objects.create_superuser(username=f"memory-superuser-{User.objects.count()}", password="pass", email="")

    def test_owner_can_edit_and_delete_personal_memory(self):
        from ..chat_memory import delete_personal_memory, edit_personal_memory, remember_knowledge

        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            user, session, message = self.create_chat()
            result = remember_knowledge(actor=user, session=session, payload={"message_ids": [message.id]})
            item = MemoryKnowledgeItem.objects.get(memory_id=result["memory_id"])

            edited = edit_personal_memory(actor=user, memory_id=item.memory_id, new_text="Насос alpha калибруется ежемесячно.")
            item.refresh_from_db()
            self.assertEqual(edited["status"], MemoryKnowledgeItem.Status.ACTIVE)
            self.assertNotIn("event_id", edited)
            self.assertTrue(edited["knowledge_file_commit"])
            self.assertIn("ежемесячно", read_knowledge_item_file(item).body)

            deleted = delete_personal_memory(actor=user, memory_id=item.memory_id)
            item.refresh_from_db()
            self.assertEqual(deleted["status"], MemoryKnowledgeItem.Status.DELETED)
            self.assertNotIn("event_id", deleted)
            self.assertTrue(deleted["knowledge_file_commit"])
            self.assertEqual(item.status, MemoryKnowledgeItem.Status.DELETED)
