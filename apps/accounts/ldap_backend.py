import json
import logging
import os
import ssl
from dataclasses import dataclass

from django.contrib.auth.backends import BaseBackend, RemoteUserBackend
from django.contrib.auth.models import Group, User
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LDAPConfig:
    host: str
    port: int
    transport: str
    search_base: str
    service_account: str
    service_password: str
    domain: str
    allow_insecure: bool
    verify_cert: bool
    ca_file: str
    user_filter: str
    group_role_map: dict[str, str]

    @classmethod
    def from_env(cls):
        transport = os.environ.get("AD_LDAP_TRANSPORT", "plain").strip().lower()
        if transport not in {"plain", "starttls", "ldaps"}:
            raise ImproperlyConfigured("AD_LDAP_TRANSPORT must be one of: plain, starttls, ldaps")

        allow_insecure = _env_bool("AD_LDAP_ALLOW_INSECURE", False)
        verify_cert = _env_bool("AD_LDAP_VERIFY_CERT", transport != "plain")
        if transport == "plain" and not allow_insecure:
            raise ImproperlyConfigured(
                "Plain LDAP requires AD_LDAP_ALLOW_INSECURE=true. "
                "Use starttls or ldaps for a secured deployment."
            )

        default_port = "636" if transport == "ldaps" else "389"
        return cls(
            host=os.environ.get("AD_LDAP_HOST", "127.0.0.1"),
            port=int(os.environ.get("AD_LDAP_PORT", default_port)),
            transport=transport,
            search_base=os.environ.get("AD_SEARCH_DN", ""),
            service_account=os.environ.get("AD_SERVICE_ACCOUNT", ""),
            service_password=os.environ.get("AD_SERVICE_PASSWORD", ""),
            domain=os.environ.get("AD_LDAP_DOMAIN", ""),
            allow_insecure=allow_insecure,
            verify_cert=verify_cert,
            ca_file=os.environ.get("AD_LDAP_CA_FILE", ""),
            user_filter=os.environ.get("AD_LDAP_USER_FILTER", "(sAMAccountName={username})"),
            group_role_map=_load_group_role_map(os.environ.get("AD_GROUP_ROLE_MAP", "")),
        )


class LDAPBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None

        username = normalize_username(username)
        try:
            config = LDAPConfig.from_env()
            user_dn, attributes = find_ad_user(config, username)
            if not user_dn:
                return None

            with ldap_connection(config, user=user_dn, password=password):
                pass

            user, _created = User.objects.get_or_create(username=username, defaults={"is_active": True})
            sync_user_from_ad(user, attributes, config.group_role_map)
            return user
        except ImproperlyConfigured as exc:
            logger.error("LDAP authentication is not configured: %s", exc)
            return None
        except Exception:
            logger.exception("LDAP authentication failed for user %s", username)
            return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


class RemoteUserLDAPBackend(RemoteUserBackend):
    create_unknown_user = True

    def clean_username(self, username):
        return normalize_username(username)

    def configure_user(self, request, user, created=True):
        sync_remote_user(user)
        return user


def sync_remote_user(user):
    try:
        config = LDAPConfig.from_env()
        _user_dn, attributes = find_ad_user(config, user.username)
        if attributes:
            sync_user_from_ad(user, attributes, config.group_role_map)
    except ImproperlyConfigured as exc:
        logger.error("Remote user AD sync is not configured: %s", exc)
    except Exception:
        logger.exception("AD profile sync failed for remote user %s", user.username)


def find_ad_user(config, username):
    if not config.search_base:
        raise ImproperlyConfigured("AD_SEARCH_DN is required for LDAP authentication")

    attributes = ["mail", "displayName", "givenName", "sn", "memberOf", "sAMAccountName", "userPrincipalName"]
    search_filter = config.user_filter.format(username=escape_filter_value(username))

    with service_connection(config) as conn:
        conn.search(config.search_base, search_filter, search_scope=_ldap().SUBTREE, attributes=attributes)
        if not conn.entries:
            return None, {}

        entry = conn.entries[0]
        return str(entry.entry_dn), entry_to_dict(entry)


def service_connection(config):
    if not config.service_account or not config.service_password:
        raise ImproperlyConfigured("AD_SERVICE_ACCOUNT and AD_SERVICE_PASSWORD are required for LDAP search")
    return ldap_connection(config, user=config.service_account, password=config.service_password)


def ldap_connection(config, *, user, password):
    ldap3 = _ldap()
    server_kwargs = {}
    if config.transport in {"starttls", "ldaps"}:
        tls_kwargs = {"validate": ssl.CERT_REQUIRED if config.verify_cert else ssl.CERT_NONE}
        if config.ca_file:
            tls_kwargs["ca_certs_file"] = config.ca_file
        server_kwargs["tls"] = ldap3.Tls(**tls_kwargs)

    server = ldap3.Server(
        config.host,
        port=config.port,
        use_ssl=config.transport == "ldaps",
        **server_kwargs,
    )
    conn = ldap3.Connection(server, user=user, password=password, auto_bind=False)
    if config.transport == "starttls":
        conn.open()
        conn.start_tls()
    if not conn.bind():
        from ldap3.core.exceptions import LDAPBindError

        raise LDAPBindError(conn.result)
    return _ConnectionContext(conn)


class _ConnectionContext:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        self.conn.unbind()


def sync_user_from_ad(user, attributes, group_role_map):
    user.email = attributes.get("mail", user.email)
    display_name = attributes.get("displayName", "")
    given_name = attributes.get("givenName", "")
    surname = attributes.get("sn", "")

    if given_name or surname:
        user.first_name = given_name
        user.last_name = surname
    elif display_name:
        user.first_name = display_name

    user.save()
    sync_user_groups(user, attributes.get("memberOf", []), group_role_map)


def sync_user_groups(user, member_of, group_role_map):
    if not group_role_map:
        return

    desired_roles = {
        role
        for ad_group in member_of
        for role in _roles_for_ad_group(ad_group, group_role_map)
    }
    if not desired_roles:
        return

    groups = [Group.objects.get_or_create(name=role)[0] for role in sorted(desired_roles)]
    user.groups.add(*groups)


def _roles_for_ad_group(ad_group, group_role_map):
    ad_group_lower = ad_group.lower()
    cn_lower = _extract_cn(ad_group).lower()
    return [
        role
        for group_name, role in group_role_map.items()
        if group_name.lower() in {ad_group_lower, cn_lower}
    ]


def _extract_cn(dn):
    first_part = dn.split(",", 1)[0]
    if first_part.lower().startswith("cn="):
        return first_part[3:]
    return dn


def normalize_username(username):
    username = username.strip()
    if "\\" in username:
        username = username.rsplit("\\", 1)[1]
    if "@" in username:
        username = username.split("@", 1)[0]
    return username


def entry_to_dict(entry):
    data = {}
    for attr in entry.entry_attributes:
        value = entry[attr].value
        if value is None:
            continue
        data[attr] = value if isinstance(value, list) else str(value)
    return data


def escape_filter_value(value):
    escape_filter_chars = _ldap_escape_filter_chars()
    return escape_filter_chars(value)


def _load_group_role_map(raw_value):
    if not raw_value:
        return {}
    try:
        payload = json.loads(raw_value)
        if not isinstance(payload, dict):
            raise ValueError
        return {str(key): str(value) for key, value in payload.items()}
    except ValueError as exc:
        raise ImproperlyConfigured("AD_GROUP_ROLE_MAP must be a JSON object") from exc


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _ldap():
    try:
        import ldap3
    except ImportError as exc:
        raise ImproperlyConfigured("LDAP auth requires ldap3. Install requirements.txt first.") from exc
    return ldap3


def _ldap_escape_filter_chars():
    try:
        from ldap3.utils.conv import escape_filter_chars
    except ImportError as exc:
        raise ImproperlyConfigured("LDAP auth requires ldap3. Install requirements.txt first.") from exc
    return escape_filter_chars
