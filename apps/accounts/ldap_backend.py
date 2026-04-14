import os
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import User
from ldap3 import Server, Connection, SUBTREE
from ldap3.core.exceptions import LDAPBindError, LDAPException


class LDAPBackend(BaseBackend):
    def __init__(self):
        self.server_uri = os.environ.get("AD_LDAP_URI", "ldap://192.168.251.1")
        self.search_base = os.environ.get("AD_SEARCH_DN", "DC=mscher,DC=local")
        self.service_account = os.environ.get("AD_SERVICE_ACCOUNT", "")
        self.service_password = os.environ.get("AD_SERVICE_PASSWORD", "")

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None

        try:
            server = Server(self.server_uri, port=389)

            user_dn = self._find_user_dn(username, password)
            if not user_dn:
                return None

            conn = Connection(server, user=user_dn, password=password, auto_bind=True)
            conn.unbind()

            user, created = User.objects.get_or_create(
                username=username,
                defaults={"is_active": True}
            )

            if created:
                self._update_user_from_ad(user, user_dn, password)

            return user

        except LDAPBindError:
            return None
        except Exception:
            return None

    def _find_user_dn(self, username, user_password=None):
        try:
            server = Server(self.server_uri, port=389)

            if self.service_account and self.service_password:
                conn = Connection(server, user=self.service_account, password=self.service_password, auto_bind=True)
            elif user_password:
                conn = Connection(server, user=self._guess_user_dn(username), password=user_password, auto_bind=True)
            else:
                return None

            conn.search(self.search_base, f"(sAMAccountName={username})", SUBTREE)

            if conn.entries:
                user_dn = str(conn.entries[0].entry_dn)
                conn.unbind()
                return user_dn

            conn.unbind()
        except Exception:
            pass
        return None

    def _guess_user_dn(self, username):
        return f"CN={username},CN=Users,{self.search_base}"

    def _update_user_from_ad(self, user, user_dn, password):
        try:
            server = Server(self.server_uri, port=389)
            conn = Connection(server, user=user_dn, password=password, auto_bind=True)

            conn.search(self.search_base, f"(sAMAccountName={user.username})", SUBTREE)
            if conn.entries:
                entry = conn.entries[0]
                if hasattr(entry, "mail") and entry.mail:
                    user.email = str(entry.mail)
                if hasattr(entry, "displayName") and entry.displayName:
                    user.first_name = str(entry.displayName)
                elif hasattr(entry, "givenName") and entry.givenName:
                    user.first_name = str(entry.givenName)
                if hasattr(entry, "sn") and entry.sn:
                    user.last_name = str(entry.sn)
                user.save()
            conn.unbind()
        except Exception:
            pass

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None