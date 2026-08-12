from contextlib import nullcontext
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings

from .ldap_backend import LDAPBackend, LDAPConfig, sync_user_groups


@pytest.mark.integration
class ADGroupRoleSyncTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="ad-role-sync-user")
        self.local_group = Group.objects.create(name="local-only")
        self.user.groups.add(self.local_group)

    @staticmethod
    def _patch_membership_writes(user):
        manager_class = user.groups.__class__
        return (
            patch.object(manager_class, "add", autospec=True),
            patch.object(manager_class, "remove", autospec=True),
        )

    @override_settings(ACCOUNTS_AD_GROUP_ROLE_SYNC=False)
    def test_disabled_sync_performs_zero_group_writes(self):
        add_patch, remove_patch = self._patch_membership_writes(self.user)
        with (
            patch(
                "apps.accounts.selectors.contract_role_configs"
            ) as contract_role_configs,
            add_patch as add_group,
            remove_patch as remove_group,
        ):
            sync_user_groups(
                self.user,
                member_of=["CN=Employees,OU=Groups,DC=example,DC=test"],
                group_role_map={"Employees": "customer"},
            )

        contract_role_configs.assert_not_called()
        add_group.assert_not_called()
        remove_group.assert_not_called()
        self.assertEqual(
            set(self.user.groups.values_list("name", flat=True)),
            {"local-only"},
        )

    @override_settings(ACCOUNTS_AD_GROUP_ROLE_SYNC=True)
    def test_unknown_mapping_is_rejected_without_group_writes(self):
        unknown_group = Group.objects.create(name="unknown-role")
        self.user.groups.add(unknown_group)
        add_patch, remove_patch = self._patch_membership_writes(self.user)

        with (
            patch(
                "apps.accounts.selectors.contract_role_configs",
                return_value={"customer": {}},
            ),
            add_patch as add_group,
            remove_patch as remove_group,
            self.assertLogs("apps.accounts.ldap_backend", level="ERROR") as logs,
        ):
            sync_user_groups(
                self.user,
                member_of=[],
                group_role_map={"Unexpected": "unknown-role"},
            )

        add_group.assert_not_called()
        remove_group.assert_not_called()
        self.assertIn("unknown contract roles: unknown-role", "\n".join(logs.output))
        self.assertIn(unknown_group, self.user.groups.all())

    @override_settings(ACCOUNTS_AD_GROUP_ROLE_SYNC=True)
    def test_missing_contract_group_is_not_created(self):
        role_name = "ad_sync_missing_role"
        self.assertFalse(Group.objects.filter(name=role_name).exists())

        with (
            patch(
                "apps.accounts.selectors.contract_role_configs",
                return_value={role_name: {}},
            ),
            self.assertLogs("apps.accounts.ldap_backend", level="ERROR") as logs,
        ):
            sync_user_groups(
                self.user,
                member_of=["CN=Employees,OU=Groups,DC=example,DC=test"],
                group_role_map={"Employees": role_name},
            )

        self.assertFalse(Group.objects.filter(name=role_name).exists())
        self.assertIn(
            f"contract groups that are not seeded: {role_name}",
            "\n".join(logs.output),
        )

    @override_settings(ACCOUNTS_AD_GROUP_ROLE_SYNC=True)
    def test_valid_mapping_fails_closed_without_audited_service(self):
        customer_group, _ = Group.objects.get_or_create(name="customer")
        technician_group, _ = Group.objects.get_or_create(name="technician")
        self.user.groups.add(technician_group)
        add_patch, remove_patch = self._patch_membership_writes(self.user)

        with (
            patch(
                "apps.accounts.selectors.contract_role_configs",
                return_value={"customer": {}, "technician": {}},
            ),
            add_patch as add_group,
            remove_patch as remove_group,
            self.assertLogs("apps.accounts.ldap_backend", level="ERROR") as logs,
        ):
            sync_user_groups(
                self.user,
                member_of=["CN=Employees,OU=Groups,DC=example,DC=test"],
                group_role_map={
                    "Employees": "customer",
                    "IT Support": "technician",
                },
            )

        add_group.assert_not_called()
        remove_group.assert_not_called()
        self.assertNotIn(customer_group, self.user.groups.all())
        self.assertIn(technician_group, self.user.groups.all())
        self.assertIn("audited AD assignment service is not available", "\n".join(logs.output))

    @override_settings(ACCOUNTS_AD_GROUP_ROLE_SYNC=True)
    def test_ldap_authentication_succeeds_when_role_sync_fails_closed(self):
        role_name = "ad_sync_auth_role"
        Group.objects.create(name=role_name)
        config = LDAPConfig(
            host="dc.example.test",
            port=636,
            transport="ldaps",
            search_base="DC=example,DC=test",
            service_account="service@example.test",
            service_password="not-used",
            domain="EXAMPLE",
            allow_insecure=False,
            verify_cert=True,
            ca_file="",
            user_filter="(sAMAccountName={username})",
            group_role_map={"Employees": role_name},
        )
        attributes = {
            "mail": "authenticated@example.test",
            "sAMAccountName": "authenticated-user",
            "memberOf": ["CN=Employees,OU=Groups,DC=example,DC=test"],
        }

        with (
            patch.object(LDAPConfig, "from_env", return_value=config),
            patch(
                "apps.accounts.ldap_backend.find_ad_user",
                return_value=("CN=Authenticated User,DC=example,DC=test", attributes),
            ),
            patch(
                "apps.accounts.ldap_backend.ldap_connection",
                return_value=nullcontext(),
            ),
            patch(
                "apps.accounts.selectors.contract_role_configs",
                return_value={role_name: {}},
            ),
            self.assertLogs("apps.accounts.ldap_backend", level="ERROR"),
        ):
            authenticated_user = LDAPBackend().authenticate(
                request=None,
                username="authenticated-user",
                password="valid-password",
            )

        self.assertIsNotNone(authenticated_user)
        self.assertEqual(authenticated_user.email, "authenticated@example.test")
        self.assertFalse(authenticated_user.groups.filter(name=role_name).exists())

    def test_ldap_authentication_and_session_restore_reject_disabled_local_user(self):
        inactive_root = get_user_model().objects.create_superuser(username="disabled-ad-root")
        inactive_root.is_active = False
        inactive_root.save(update_fields=["is_active"])
        config = LDAPConfig(
            host="dc.example.test",
            port=636,
            transport="ldaps",
            search_base="DC=example,DC=test",
            service_account="service@example.test",
            service_password="not-used",
            domain="EXAMPLE",
            allow_insecure=False,
            verify_cert=True,
            ca_file="",
            user_filter="(sAMAccountName={username})",
            group_role_map={},
        )

        backend = LDAPBackend()
        with (
            patch.object(LDAPConfig, "from_env", return_value=config),
            patch(
                "apps.accounts.ldap_backend.find_ad_user",
                return_value=("CN=Disabled Root,DC=example,DC=test", {}),
            ),
            patch("apps.accounts.ldap_backend.ldap_connection", return_value=nullcontext()),
            patch("apps.accounts.ldap_backend.sync_user_from_ad") as sync_user,
            self.assertLogs("apps.accounts.ldap_backend", level="WARNING"),
        ):
            authenticated = backend.authenticate(
                request=None,
                username="disabled-ad-root",
                password="valid-ad-password",
            )

        self.assertIsNone(authenticated)
        self.assertIsNone(backend.get_user(inactive_root.pk))
        sync_user.assert_not_called()

    def test_profile_sync_cannot_restore_stale_privileged_flags(self):
        from .ldap_backend import sync_user_from_ad

        root = get_user_model().objects.create_superuser(username="ldap-stale-root")
        stale_instance = get_user_model().objects.get(pk=root.pk)
        get_user_model().objects.filter(pk=root.pk).update(
            is_active=False,
            is_staff=False,
            is_superuser=False,
        )

        sync_user_from_ad(
            stale_instance,
            {
                "mail": "updated-profile@example.test",
                "givenName": "Новый",
                "sn": "Профиль",
                "sAMAccountName": stale_instance.username,
            },
            {},
        )

        root.refresh_from_db()
        self.assertFalse(root.is_active)
        self.assertFalse(root.is_staff)
        self.assertFalse(root.is_superuser)
        self.assertEqual(root.email, "updated-profile@example.test")
