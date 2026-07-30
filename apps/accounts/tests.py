import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.urls import reverse

import apps.core.json_utils as json_utils
from .ldap_backend import LDAPConfig, normalize_username, sync_user_groups
from .models import ExternalIdentity, GroupProfile
from .services import scope_tokens_for_principal, upsert_ad_identity_from_attributes
from .views import MANUAL_AUTH_SESSION_KEY


class LDAPAuthConfigTests(TestCase):
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


class PortalAuthViewTests(TestCase):
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
