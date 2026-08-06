import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.db.models.deletion import ProtectedError
from django.contrib.auth.models import Group, Permission
from django.contrib.auth import get_user_model
from django.urls import reverse

import apps.core.json_utils as json_utils
from .ldap_backend import LDAPConfig, normalize_username, sync_user_groups
from .models import AccessAssignmentAudit, ExternalIdentity, GroupProfile
from .department_policy import (
    ORGANIZATION_ROOT_DEPARTMENT_NAME,
    UNASSIGNED_USER_DEPARTMENT_NAME,
)
from .selectors import effective_access_for_user, role_risk_markers
from .services import (
    apply_role_assignment,
    preview_role_assignment,
    scope_tokens_for_principal,
    upsert_ad_identity_from_attributes,
)
from .views import MANUAL_AUTH_SESSION_KEY


@pytest.mark.unit
class LDAPConfigParsingTests(SimpleTestCase):
    def test_normalize_username_accepts_windows_and_upn_formats(self):
        self.assertEqual(normalize_username("MSCHER\\ivanov"), "ivanov")
        self.assertEqual(normalize_username("ivanov@mscher.local"), "ivanov")
        self.assertEqual(normalize_username(" ivanov "), "ivanov")

    def test_plain_ldap_requires_explicit_insecure_flag(self):
        with patch.dict(
            "os.environ",
            {
                "AD_LDAP_TRANSPORT": "plain",
                "AD_LDAP_ALLOW_INSECURE": "false",
                "AD_SEARCH_DN": "DC=mscher,DC=local",
            },
            clear=True,
        ):
            with self.assertRaises(ImproperlyConfigured):
                LDAPConfig.from_env()

    def test_plain_ldap_config_supports_role_map(self):
        with patch.dict(
            "os.environ",
            {
                "AD_LDAP_TRANSPORT": "plain",
                "AD_LDAP_ALLOW_INSECURE": "true",
                "AD_LDAP_HOST": "dc01.mscher.local",
                "AD_SEARCH_DN": "DC=mscher,DC=local",
                "AD_GROUP_ROLE_MAP": '{"IT Support":"technician"}',
            },
            clear=True,
        ):
            config = LDAPConfig.from_env()

        self.assertEqual(config.host, "dc01.mscher.local")
        self.assertEqual(config.port, 389)
        self.assertEqual(config.transport, "plain")
        self.assertEqual(config.group_role_map, {"IT Support": "technician"})


@pytest.mark.integration
class LDAPAuthConfigTests(TestCase):
    def test_ad_group_sync_removes_only_ad_managed_missing_roles(self):
        User = get_user_model()
        user = User.objects.create_user(username="ldap-user")
        technician, _ = Group.objects.get_or_create(name="technician")
        local_group, _ = Group.objects.get_or_create(name="local-only")
        user.groups.add(technician, local_group)

        sync_user_groups(
            user,
            member_of=[],
            group_role_map={"IT Support": "technician", "Employees": "customer"},
        )

        group_names = set(user.groups.values_list("name", flat=True))
        self.assertNotIn("technician", group_names)
        self.assertIn("local-only", group_names)

    def test_ad_identity_link_stores_allowlisted_attributes_and_maps_scope_token(self):
        User = get_user_model()
        user = User.objects.create_user(username="ad-linked-user")

        identity = upsert_ad_identity_from_attributes(
            user=user,
            domain="EXAMPLE",
            attributes={
                "objectSid": "S-1-5-21-linked",
                "sAMAccountName": "ad-linked-user",
                "userPrincipalName": "ad-linked-user@example.test",
                "unicodePwd": "must-not-store",
            },
        )

        self.assertEqual(identity.sync_status, ExternalIdentity.SyncStatus.VERIFIED)
        self.assertNotIn("unicodePwd", identity.attributes)
        self.assertEqual(scope_tokens_for_principal(sid="S-1-5-21-linked"), {f"user:{user.id}"})


@pytest.mark.integration
class PortalAuthViewTests(TestCase):
    @staticmethod
    def _remote_user_middleware():
        from config.settings import build_middleware

        middleware = build_middleware(False)
        middleware.insert(
            middleware.index("django.contrib.auth.middleware.AuthenticationMiddleware") + 1,
            "apps.accounts.middleware.ManualAuthAwareRemoteUserMiddleware",
        )
        return middleware

    @patch("apps.accounts.ldap_backend.sync_remote_user")
    def test_automatic_public_requests_do_not_start_remote_user_session(self, _sync_remote_user):
        """Параллельные служебные запросы не создают competing session/CSRF cookie."""
        with override_settings(
            AUTHENTICATION_BACKENDS=["apps.accounts.ldap_backend.RemoteUserLDAPBackend"],
            MIDDLEWARE=self._remote_user_middleware(),
        ):
            for path, request_uri in (
                ("/", "/favicon.ico"),
                ("/service-worker.js", "/service-worker.js"),
            ):
                with self.subTest(path=path):
                    isolated_client = self.client_class(enforce_csrf_checks=True)
                    response = isolated_client.get(
                        path,
                        REMOTE_USER="DOMAIN\\parallel-asset-user",
                        REQUEST_URI=request_uri,
                    )

                    self.assertNotIn("sessionid", response.cookies)
                    self.assertNotIn("csrftoken", response.cookies)
                    self.assertNotIn("_auth_user_id", isolated_client.session)
                    self.assertFalse(
                        get_user_model().objects.filter(username="parallel-asset-user").exists()
                    )

    @patch("apps.accounts.ldap_backend.sync_remote_user")
    def test_missing_static_file_does_not_start_remote_user_session(self, _sync_remote_user):
        with override_settings(
            AUTHENTICATION_BACKENDS=["apps.accounts.ldap_backend.RemoteUserLDAPBackend"],
            MIDDLEWARE=self._remote_user_middleware(),
        ):
            isolated_client = self.client_class(enforce_csrf_checks=True)

            isolated_client.get(
                "/static/missing-preload.js",
                REMOTE_USER="DOMAIN\\missing-static-user",
                REQUEST_URI="/static/missing-preload.js",
            )

            self.assertNotIn("_auth_user_id", isolated_client.session)
            self.assertFalse(
                get_user_model().objects.filter(username="missing-static-user").exists()
            )

    def test_logout_keeps_remote_user_from_immediate_relogin(self):
        User = get_user_model()
        remote_user = User.objects.create_user(username="remote-user")
        self.client.force_login(remote_user)

        response = self.client.post(reverse("logout"), REMOTE_USER="DOMAIN\\remote-user")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session[MANUAL_AUTH_SESSION_KEY])

        response = self.client.get(reverse("core:dashboard"), REMOTE_USER="DOMAIN\\remote-user")
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_manual_login_takes_precedence_over_remote_user(self):
        User = get_user_model()
        local_user = User.objects.create_user(username="local-user", password="local-pass")

        response = self.client.post(
            reverse("login"),
            {"username": "local-user", "password": "local-pass"},
            REMOTE_USER="DOMAIN\\remote-user",
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), local_user.pk)
        self.assertTrue(self.client.session[MANUAL_AUTH_SESSION_KEY])

        response = self.client.get(reverse("core:dashboard"), REMOTE_USER="DOMAIN\\remote-user")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.wsgi_request.user.username, "local-user")


@pytest.mark.integration
@pytest.mark.slow
class SeedRolesCommandTests(TestCase):
    """seed_roles создаёт группы ролей контракта + memory-группы и
    синхронизирует их GroupProfile (ADR-0034). Работает на изолированной
    рабочей копии контракта ролей (override LOCAL_BUSINESS_ROLE_RULES_FILE),
    чтобы тест не зависел от состояния data/contracts/ и не писал в него."""

    EXPECTED_ROLE_GROUPS = {"customer", "technician", "manager", "admin", "doctor"}
    EXPECTED_MEMORY_GROUPS = {
        "memory_admin",
        "memory_auditor",
        "memory_index_operator",
        "memory_observer",
    }

    def setUp(self):
        from apps.core.contract_store import _reset_for_tests

        base_role_rules = json_utils.load_json_file("contracts/role_rules.json")
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        role_file = Path(self._tmpdir.name) / "role_rules.json"
        role_file.write_text(json.dumps(base_role_rules, ensure_ascii=False), encoding="utf-8")

        self._override = override_settings(LOCAL_BUSINESS_ROLE_RULES_FILE=role_file)
        self._override.enable()
        self.addCleanup(self._override.disable)

        _reset_for_tests()
        self.addCleanup(_reset_for_tests)

    def test_seed_roles_creates_all_expected_groups(self):
        call_command("seed_roles")

        expected = self.EXPECTED_ROLE_GROUPS | self.EXPECTED_MEMORY_GROUPS
        created = set(
            Group.objects.filter(name__in=expected).values_list("name", flat=True)
        )
        self.assertEqual(created, expected)

    def test_doctor_and_admin_groups_get_predefined_profile_with_text(self):
        call_command("seed_roles")

        for name in ("doctor", "admin"):
            group = Group.objects.get(name=name)
            profile = group.profile
            self.assertTrue(profile.is_predefined)
            self.assertTrue(profile.title.strip(), f"{name}: пустой title")
            self.assertTrue(profile.description.strip(), f"{name}: пустой description")

    def test_seed_roles_is_idempotent_and_restores_edited_description(self):
        call_command("seed_roles")
        expected = self.EXPECTED_ROLE_GROUPS | self.EXPECTED_MEMORY_GROUPS
        groups_after_first_run = Group.objects.filter(name__in=expected).count()

        doctor_profile = Group.objects.get(name="doctor").profile
        original_description = doctor_profile.description
        doctor_profile.description = "испорчено вручную"
        doctor_profile.save(update_fields=["description"])

        call_command("seed_roles")

        # Повторный вызов не плодит новые группы...
        self.assertEqual(
            Group.objects.filter(name__in=expected).count(), groups_after_first_run
        )
        # ...и восстанавливает описание, испорченное вручную.
        doctor_profile.refresh_from_db()
        self.assertEqual(doctor_profile.description, original_description)
        self.assertNotEqual(doctor_profile.description, "испорчено вручную")


@pytest.mark.integration
class AccessAssignmentServiceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.manager_group, _ = Group.objects.get_or_create(name="manager")
        self.customer_group, _ = Group.objects.get_or_create(name="customer")
        self.technical_group, _ = Group.objects.get_or_create(name="memory_auditor")
        self.actor = User.objects.create_user(username="access-actor")
        self.actor.groups.add(self.manager_group)
        self.target = User.objects.create_user(username="access-target")
        self.target.groups.add(self.customer_group, self.technical_group)

    def test_risky_assignment_requires_bound_preview_and_preserves_technical_group(self):
        preview = preview_role_assignment(
            actor=self.actor,
            target_user=self.target,
            selected_role_names=["manager"],
        )

        self.assertTrue(preview["requires_confirmation"])
        with self.assertRaisesMessage(ValidationError, "явного подтверждения"):
            apply_role_assignment(
                actor=self.actor,
                target_user=self.target,
                selected_role_names=["manager"],
                preview_token=preview["preview_token"],
                risk_confirmed=False,
            )

        target, audit = apply_role_assignment(
            actor=self.actor,
            target_user=self.target,
            selected_role_names=["manager"],
            preview_token=preview["preview_token"],
            risk_confirmed=True,
        )

        self.assertEqual(set(target.groups.values_list("name", flat=True)), {"manager", "memory_auditor"})
        self.assertEqual(audit.roles_before, ["customer"])
        self.assertEqual(audit.roles_after, ["manager"])
        self.assertTrue(audit.risk_confirmed)
        self.assertNotIn("access-target", str(audit.roles_after))

    def test_role_risk_markers_ignore_display_metadata(self):
        markers = role_risk_markers(
            "metadata-only",
            {"display_name": "Служебное название", "description": "Служебное описание"},
        )

        self.assertEqual(markers, [])

    def test_role_risk_markers_do_not_copy_editable_description_to_audit(self):
        with patch(
            "apps.accounts.selectors.capability_catalog",
            return_value={
                "dangerous_capability": {
                    "label": "Критическое право",
                    "description": "Иван Иванов, телефон 000 — не должно попасть в аудит",
                    "risk": "critical",
                }
            },
        ):
            markers = role_risk_markers("manager", {"dangerous_capability": True})

        self.assertEqual(markers, ["manager: Критическое право — критический риск"])
        self.assertNotIn("Иван Иванов", markers[0])

    def test_unknown_and_service_metadata_roles_are_rejected(self):
        for role_name in ("unknown-role", "$capabilities"):
            with self.subTest(role_name=role_name):
                with self.assertRaises(ValidationError):
                    preview_role_assignment(
                        actor=self.actor,
                        target_user=self.target,
                        selected_role_names=[role_name],
                    )

    def test_self_escalation_uses_same_risk_confirmation(self):
        admin_group, _ = Group.objects.get_or_create(name="admin")
        preview = preview_role_assignment(
            actor=self.actor,
            target_user=self.actor,
            selected_role_names=["admin"],
        )

        self.assertTrue(preview["requires_confirmation"])
        with self.assertRaises(ValidationError):
            apply_role_assignment(
                actor=self.actor,
                target_user=self.actor,
                selected_role_names=["admin"],
                preview_token=preview["preview_token"],
                risk_confirmed=False,
            )
        actor, audit = apply_role_assignment(
            actor=self.actor,
            target_user=self.actor,
            selected_role_names=["admin"],
            preview_token=preview["preview_token"],
            risk_confirmed=True,
        )
        self.assertIn(admin_group, actor.groups.all())
        self.assertEqual(audit.actor_id, audit.target_user_id)

    def test_preview_is_bound_to_actor_target_selection_and_current_roles(self):
        preview = preview_role_assignment(
            actor=self.actor,
            target_user=self.target,
            selected_role_names=["manager"],
        )
        other = get_user_model().objects.create_user(username="other-target")
        with self.assertRaisesMessage(ValidationError, "другому пользователю"):
            apply_role_assignment(
                actor=self.actor,
                target_user=other,
                selected_role_names=["manager"],
                preview_token=preview["preview_token"],
                risk_confirmed=True,
            )

        with self.assertRaisesMessage(ValidationError, "изменились после предпросмотра"):
            apply_role_assignment(
                actor=self.actor,
                target_user=self.target,
                selected_role_names=["customer"],
                preview_token=preview["preview_token"],
                risk_confirmed=True,
            )

        self.target.groups.remove(self.customer_group)
        with self.assertRaisesMessage(ValidationError, "уже изменены"):
            apply_role_assignment(
                actor=self.actor,
                target_user=self.target,
                selected_role_names=["manager"],
                preview_token=preview["preview_token"],
                risk_confirmed=True,
            )
        self.assertFalse(AccessAssignmentAudit.objects.exists())

    def test_effective_access_explains_all_supported_sources(self):
        permission = Permission.objects.select_related("content_type").first()
        self.target.user_permissions.add(permission)
        self.target.is_staff = True
        self.target.save(update_fields=["is_staff"])

        access = effective_access_for_user(self.target)

        self.assertEqual(access["roles"][0]["code"], "customer")
        self.assertEqual(access["technical_groups"][0]["code"], "memory_auditor")
        self.assertIn("is_staff", {item["source"] for item in access["flags"]})
        self.assertIn(
            f"{permission.content_type.app_label}.{permission.codename}",
            {item["code"] for item in access["django_permissions"]},
        )
        self.assertTrue(any(source["type"] == "role" for item in access["capabilities"] for source in item["sources"]))

    def test_superuser_access_explains_capabilities_without_role_groups(self):
        superuser = get_user_model().objects.create_superuser(username="access-root")

        access = effective_access_for_user(superuser)

        self.assertTrue(access["capabilities"])
        self.assertTrue(
            all(
                any(source["type"] == "is_superuser" for source in capability["sources"])
                for capability in access["capabilities"]
            )
        )

    def test_management_command_runs_e2e_and_rolls_back_data(self):
        call_command("access_management_e2e")

        User = get_user_model()
        self.assertFalse(User.objects.filter(username__startswith="__access_management_e2e_").exists())


@pytest.mark.integration
class MandatoryUserDepartmentTests(TestCase):
    def test_programmatic_user_without_department_is_placed_in_safe_quarantine(self):
        user = get_user_model().objects.create_user(username="department-quarantine")

        self.assertTrue(user.requires_department_assignment)
        self.assertEqual(user.department.name, UNASSIGNED_USER_DEPARTMENT_NAME)
        self.assertEqual(user.department.parent.name, ORGANIZATION_ROOT_DEPARTMENT_NAME)
        self.assertIsNone(user.department.parent.parent_id)

    def test_explicit_department_is_preserved_and_protected_from_deletion(self):
        from apps.core.models import Department

        department = Department.objects.create(name="Обязательное подразделение теста")
        user = get_user_model().objects.create_user(
            username="department-explicit",
            department=department,
        )

        self.assertFalse(user.requires_department_assignment)
        self.assertEqual(user.department_id, department.pk)
        with self.assertRaises(ProtectedError):
            department.delete()
