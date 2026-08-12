"""Тесты политик доступа, проекции source adapter и privacy pipeline."""
import pytest
from django.core.exceptions import PermissionDenied

from apps.memory.tests._common import *  # noqa: F401,F403


class MemoryPolicyAndAuditTests(MemoryModelFactoryMixin, TestCase):
    databases = RUNTIME_DATABASES
    def test_user_scope_tokens_and_manage_policy(self):
        group = Group.objects.create(name="memory_admins")
        user = User.objects.create_user(username="memory-user", password="pass", is_staff=True)
        user.groups.add(group)

        tokens = user_scope_tokens(user)

        self.assertIn("org:default", tokens)
        self.assertIn(f"user:{user.id}", tokens)
        self.assertIn("role:memory_admins", tokens)
        self.assertTrue(can_manage_memory(user))
        self.assertFalse(can_manage_memory(User(username="anonymous")))

    def test_search_document_access_respects_scope_status_and_superuser(self):
        user = User.objects.create_user(username="scoped-user", password="pass")
        superuser = User.objects.create_superuser(username="memory-root", password="pass")
        document = self.create_search_document(scope_tokens=[f"user:{user.id}"])

        self.assertTrue(can_access_search_document(user, document))

        document.index_status = MemorySearchDocument.IndexStatus.DELETED
        document.save(update_fields=["index_status", "updated_at"])

        self.assertFalse(can_access_search_document(user, document))
        self.assertTrue(can_access_search_document(superuser, document))

    def test_record_access_audit_uses_hashes_ids_and_scope_tokens_without_raw_query_field(self):
        group = Group.objects.create(name="operators")
        user = User.objects.create_user(username="audit-user", password="pass")
        user.groups.add(group)

        audit = record_access_audit(
            actor=user,
            request_id="req-audit-1",
            query_hash="sha256:abc",
            returned_document_ids=["document-1"],
            returned_fact_ids=["fact-1"],
            policy_decision="allowed",
            retrieval_trace={"backend": "test"},
        )

        self.assertEqual(audit.tool_name, "memory.search")
        self.assertEqual(audit.query_hash, "sha256:abc")
        self.assertEqual(audit.returned_document_ids, ["document-1"])
        self.assertEqual(audit.returned_fact_ids, ["fact-1"])
        self.assertEqual(audit.allowed_scope_tokens, sorted({"org:default", f"user:{user.id}", "role:operators"}))
        self.assertNotIn("query", {field.name for field in MemoryAccessAudit._meta.fields})
        self.assertEqual(str(audit), "req-audit-1:allowed")

    def test_memory_group_membership_preview_apply_preserves_contract_roles_and_audits(self):
        from apps.memory.access_services import (
            apply_memory_group_membership,
            preview_memory_group_membership,
        )
        from apps.memory.models import MemoryGroupMembershipAudit

        actor = User.objects.create_superuser(username="memory-membership-root")
        target = User.objects.create_user(username="memory-membership-target")
        role, _ = Group.objects.get_or_create(name=ROLE_CUSTOMER)
        observer, _ = Group.objects.get_or_create(name="memory_observer")
        Group.objects.get_or_create(name="memory_auditor")
        target.groups.add(role, observer)

        preview = preview_memory_group_membership(
            actor=actor,
            target_user=target,
            selected_group_names=["memory_auditor"],
            reason="Передача обязанностей ревью.",
        )
        target, audit = apply_memory_group_membership(
            actor=actor,
            target_user=target,
            selected_group_names=["memory_auditor"],
            reason="Передача обязанностей ревью.",
            preview_token=preview["preview_token"],
            confirmed=True,
        )

        self.assertEqual(
            set(target.groups.values_list("name", flat=True)),
            {ROLE_CUSTOMER, "memory_auditor"},
        )
        self.assertEqual(audit.groups_added, ["memory_auditor"])
        self.assertEqual(audit.groups_removed, ["memory_observer"])
        self.assertEqual(MemoryGroupMembershipAudit.objects.count(), 1)

    def test_memory_group_membership_rejects_non_superuser_and_stale_target(self):
        from apps.memory.access_services import (
            apply_memory_group_membership,
            preview_memory_group_membership,
        )

        actor = User.objects.create_superuser(username="memory-membership-stale-root")
        target = User.objects.create_user(username="memory-membership-stale-target")
        observer = Group.objects.create(name="memory_observer")
        auditor = Group.objects.create(name="memory_auditor")
        outsider = User.objects.create_user(username="memory-membership-outsider")
        with self.assertRaises(PermissionDenied):
            preview_memory_group_membership(
                actor=outsider,
                target_user=target,
                selected_group_names=[observer.name],
                reason="Недопустимо.",
            )

        preview = preview_memory_group_membership(
            actor=actor,
            target_user=target,
            selected_group_names=[observer.name],
            reason="Проверка stale state.",
        )
        target.groups.add(auditor)
        with self.assertRaisesMessage(ValidationError, "изменился после предпросмотра"):
            apply_memory_group_membership(
                actor=actor,
                target_user=target,
                selected_group_names=[observer.name],
                reason="Проверка stale state.",
                preview_token=preview["preview_token"],
                confirmed=True,
            )


@pytest.mark.integration
class MemorySourceAdapterProjectionTests(TestCase):
    databases = RUNTIME_DATABASES

    @classmethod
    def setUpTestData(cls):
        cls.department = Department.objects.create(name="Диагностика")
        cls.device = MedicalDevice.objects.create(
            name="УЗИ аппарат",
            serial_number="USA-ADAPTER-001",
            department=cls.department,
        )
        cls.customer = User.objects.create_user(username="adapter-customer", password="pass")
        cls.technician = User.objects.create_user(username="adapter-tech", password="pass")
        cls.manager = User.objects.create_user(username="adapter-manager", password="pass")
        cls.doctor = User.objects.create_user(username="adapter-doctor", password="pass")
        cls.outsider = User.objects.create_user(username="adapter-outsider", password="pass")
        for role, user in (
            (ROLE_CUSTOMER, cls.customer),
            (ROLE_TECHNICIAN, cls.technician),
            (ROLE_MANAGER, cls.manager),
            ("doctor", cls.doctor),
        ):
            group, _created = Group.objects.get_or_create(name=role)
            user.groups.add(group)
        cls.board = Board.objects.create(title="Adapter Board", slug="adapter-board")
        cls.board.allowed_groups.set(
            Group.objects.filter(name__in=[ROLE_CUSTOMER, ROLE_TECHNICIAN, ROLE_MANAGER])
        )

    def test_workorder_adapter_reconcile_indexes_search_and_analytics_with_access_check(self):
        workorder = WorkOrder.objects.create(
            title="Проверить адаптер памяти",
            description="Уникальный маркер universal-workorder-alpha для поиска.",
            department=self.department,
            author=self.customer,
            assignee=self.technician,
            board=self.board,
            device=self.device,
            status=WorkOrderStatus.NEW,
        )

        with TemporaryDirectory() as tmpdir:
            with self.settings(DATA_DIR=Path(tmpdir) / "data", LOCAL_BUSINESS_MEMORY_VECTOR_BACKEND="disabled"):
                call_command("source_adapter_reconcile", source_code="workorders", target="all", backend="fulltext", verbosity=0)
                from ..retrieval import memory_search

                visible = memory_search(
                    actor=self.manager,
                    query="universal workorder alpha",
                    search_mode="source_explicit",
                    include_source_data=True,
                    ranking_profile="source_content",
                    limit=5,
                    source_codes=["workorders"],
                )
                hidden = memory_search(
                    actor=self.outsider,
                    query="universal workorder alpha",
                    search_mode="source_explicit",
                    include_source_data=True,
                    ranking_profile="source_content",
                    limit=5,
                    source_codes=["workorders"],
                )

        self.assertTrue(MemorySearchDocument.objects.filter(source_object__source__code="workorders").exists())
        self.assertEqual(visible["items"][0]["source_object_id"], str(workorder.pk))
        self.assertEqual(visible["items"][0]["kind"], "source_data")
        self.assertEqual(hidden["items"], [])
        self.assertTrue(AnalyticsContentObject.objects.filter(source__code="workorders", source_object_id=str(workorder.pk)).exists())
        self.assertTrue(AnalyticsFact.objects.filter(fact_type="workorder_created").exists())

    def test_waiting_list_adapter_uses_pii_off_without_pii_audit(self):
        entry = WaitingListEntry.objects.create(
            author=self.customer,
            patient_name="Скрытый Пациент",
            patient_phone="+7 (900) 111-22-33",
            service_id="s1",
            comment="Контрольный маркер waiting-list-beta для поиска.",
        )

        with TemporaryDirectory() as tmpdir:
            with self.settings(DATA_DIR=Path(tmpdir) / "data", LOCAL_BUSINESS_MEMORY_VECTOR_BACKEND="disabled"):
                call_command("source_adapter_reconcile", source_code="waiting_list", target="all", backend="fulltext", verbosity=0)
                from ..retrieval import memory_search

                result = memory_search(
                    actor=self.doctor,
                    query="waiting list beta",
                    search_mode="source_explicit",
                    include_source_data=True,
                    ranking_profile="source_content",
                    limit=5,
                    source_codes=["waiting_list"],
                )

        self.assertEqual(result["items"][0]["source_object_id"], str(entry.pk))
        self.assertFalse(
            MemoryIngestionIssue.objects.filter(
                source__code="waiting_list",
                issue_kind=MemoryIngestionIssue.IssueKind.PII_AUDIT,
            ).exists()
        )
        source_object = MemorySourceObject.objects.get(source__code="waiting_list", object_id=str(entry.pk))
        self.assertNotIn("Скрытый Пациент", (source_object.metadata or {}).get("safe_text", ""))
        self.assertTrue(AnalyticsFact.objects.filter(fact_type="waiting_list_entry_created").exists())


class MemoryPrivacyPipelineTests(MemoryModelFactoryMixin, TestCase):
    databases = RUNTIME_DATABASES
    secret_key = "test-only-pseudonym-secret"

    def test_synthetic_russian_pii_is_redacted_without_real_examples(self):
        from ..deidentification import redact_text

        raw_text = (
            "Синтетическая карточка: ФИО: Тестов Тест Тестович; "
            "телефон +7 000 000-00-00; email synthetic.patient@example.test; "
            "СНИЛС 000-000-000 00; паспорт 0000 000000."
        )

        result = redact_text(raw_text)

        self.assertFalse(result.blocked)
        self.assertNotIn("Тестов Тест Тестович", result.safe_text)
        self.assertNotIn("+7 000 000-00-00", result.safe_text)
        self.assertNotIn("synthetic.patient@example.test", result.safe_text)
        self.assertNotIn("000-000-000 00", result.safe_text)
        self.assertNotIn("0000 000000", result.safe_text)
        self.assertIn("[RU_FULL_NAME]", result.safe_text)
        self.assertIn("[PHONE]", result.safe_text)
        self.assertIn("[EMAIL]", result.safe_text)
        self.assertIn("[SNILS]", result.safe_text)
        self.assertIn("[PASSPORT]", result.safe_text)

    def test_pseudonyms_are_stable_with_caller_provided_secret(self):
        from ..deidentification import deidentify_text

        raw_text = "ФИО: Тестов Тест Тестович; телефон +7 000 000-00-00."

        first = deidentify_text(raw_text, secret_key=self.secret_key)
        second = deidentify_text(raw_text, secret_key=self.secret_key)
        changed_secret = deidentify_text(raw_text, secret_key="different-test-only-secret")

        self.assertFalse(first.blocked)
        self.assertEqual(first.safe_text, second.safe_text)
        self.assertEqual([item.replacement for item in first.replacements], [item.replacement for item in second.replacements])
        self.assertNotEqual(first.safe_text, changed_secret.safe_text)
        self.assertNotIn("Тестов Тест Тестович", first.safe_text)
        self.assertNotIn("+7 000 000-00-00", first.safe_text)

    def test_secret_material_blocks_deidentification(self):
        from ..deidentification import deidentify_text
        from ..security import scan_for_secrets

        raw_text = "Техническая заметка: api_key=not-a-real-placeholder-value"

        dlp_result = scan_for_secrets(raw_text)
        deidentified = deidentify_text(raw_text, secret_key=self.secret_key)

        self.assertTrue(dlp_result.blocked)
        self.assertEqual(dlp_result.reason, "credential_material_detected")
        self.assertTrue(deidentified.blocked)
        self.assertEqual(deidentified.reason, "credential_material_detected")
        self.assertEqual(deidentified.safe_text, "")

    def test_secret_scanner_detects_russian_password_assignment(self):
        from ..security import scan_for_secrets

        result = scan_for_secrets("Запомни пароль: E2E-Secret-Value-987!")

        self.assertTrue(result.blocked)
        self.assertEqual(result.findings[0].finding_type, "credential_assignment")
