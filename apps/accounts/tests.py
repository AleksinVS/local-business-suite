from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model

from .ldap_backend import LDAPConfig, normalize_username, sync_user_groups


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
        technician = Group.objects.create(name="technician")
        local_group = Group.objects.create(name="local-only")
        user.groups.add(technician, local_group)

        sync_user_groups(
            user,
            member_of=[],
            group_role_map={"IT Support": "technician", "Employees": "customer"},
        )

        group_names = set(user.groups.values_list("name", flat=True))
        self.assertNotIn("technician", group_names)
        self.assertIn("local-only", group_names)
