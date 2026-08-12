import json
import logging
import os
import ssl
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend, RemoteUserBackend
from django.contrib.auth.models import Group
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
            raise ImproperlyConfigured(
                "AD_LDAP_TRANSPORT must be one of: plain, starttls, ldaps"
            )

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
            user_filter=os.environ.get(
                "AD_LDAP_USER_FILTER", "(sAMAccountName={username})"
            ),
            group_role_map=_load_group_role_map(
                os.environ.get("AD_GROUP_ROLE_MAP", "")
            ),
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

            from .services import (
                get_or_create_external_user,
                refresh_external_user_authentication_state,
            )

            user, _created = get_or_create_external_user(
                username=username,
                audit_callback=record_external_user_creation_audit,
            )
            user = refresh_external_user_authentication_state(user)
            if not user.is_active:
                logger.warning("LDAP login rejected for disabled local user %s", username)
                return None
            user = sync_user_from_ad(user, attributes, config.group_role_map)
            user = refresh_external_user_authentication_state(user)
            if not user.is_active:
                logger.warning("LDAP login rejected for disabled local user %s", username)
                return None
            return user
        except ImproperlyConfigured as exc:
            logger.error("LDAP authentication is not configured: %s", exc)
            return None
        except Exception:
            logger.exception("LDAP authentication failed for user %s", username)
            return None

    def get_user(self, user_id):
        UserModel = get_user_model()
        try:
            user = UserModel.objects.get(pk=user_id)
        except UserModel.DoesNotExist:
            return None
        from .services import refresh_external_user_authentication_state

        user = refresh_external_user_authentication_state(user)
        return user if user.is_active else None


class RemoteUserLDAPBackend(RemoteUserBackend):
    create_unknown_user = True

    def authenticate(self, request, remote_user):
        if not remote_user:
            return None
        from .services import get_or_create_external_user

        username = self.clean_username(remote_user)
        user, created = get_or_create_external_user(
            username=username,
            audit_callback=record_external_user_creation_audit,
        )
        user = self.configure_user(request, user, created=created)
        return user if self.user_can_authenticate(user) else None

    def clean_username(self, username):
        return normalize_username(username)

    def get_user(self, user_id):
        user = get_user_model().objects.filter(pk=user_id).first()
        if user is None:
            return None
        from .services import refresh_external_user_authentication_state

        user = refresh_external_user_authentication_state(user)
        return user if user.is_active else None

    def configure_user(self, request, user, created=True):
        return sync_remote_user(user)


def record_external_user_creation_audit(before, after):
    """Зафиксировать автоматическое создание без раскрытия principal."""
    from apps.settings_center.models import SettingsChange
    from apps.settings_center.registry import get_registry
    from apps.settings_center.services import record_settings_change

    from .services import user_profile_audit_snapshot

    record_settings_change(
        actor=None,
        descriptor=get_registry().get("accounts.users.local_management"),
        action=SettingsChange.Action.USER_CREATE,
        status=SettingsChange.Status.APPLIED,
        before=user_profile_audit_snapshot(before),
        after=user_profile_audit_snapshot(after),
        validation_result={"valid": True, "source": "external_authentication"},
    )


def record_external_directory_sync_audit(
    profile_before, profile_after, identity_before, identity_after
):
    """Атомарно зафиксировать безопасные profile/AD fingerprints системной sync."""
    from apps.settings_center.models import SettingsChange
    from apps.settings_center.registry import get_registry
    from apps.settings_center.services import record_settings_change

    from .services import external_identity_audit_snapshot, user_profile_audit_snapshot

    if profile_before != profile_after:
        record_settings_change(
            actor=None,
            descriptor=get_registry().get("accounts.users.local_management"),
            action=SettingsChange.Action.USER_UPDATE,
            status=SettingsChange.Status.APPLIED,
            before=user_profile_audit_snapshot(profile_before),
            after=user_profile_audit_snapshot(profile_after),
            validation_result={"valid": True, "source": "external_authentication"},
        )
    if identity_before != identity_after:
        record_settings_change(
            actor=None,
            descriptor=get_registry().get("accounts.user.ad_identity_link"),
            action=SettingsChange.Action.AD_LINK,
            status=SettingsChange.Status.APPLIED,
            before=external_identity_audit_snapshot(identity_before),
            after=external_identity_audit_snapshot(identity_after),
            validation_result={"valid": True, "source": "external_authentication"},
        )


def sync_remote_user(user):
    from .services import refresh_external_user_authentication_state

    try:
        config = LDAPConfig.from_env()
        _user_dn, attributes = find_ad_user(config, user.username)
        if attributes:
            return sync_user_from_ad(user, attributes, config.group_role_map)
    except ImproperlyConfigured as exc:
        logger.error("Remote user AD sync is not configured: %s", exc)
    except Exception:
        logger.exception("AD profile sync failed for remote user %s", user.username)
    return refresh_external_user_authentication_state(user)


def find_ad_user(config, username):
    if not config.search_base:
        raise ImproperlyConfigured("AD_SEARCH_DN is required for LDAP authentication")

    attributes = [
        "mail",
        "displayName",
        "givenName",
        "sn",
        "memberOf",
        "sAMAccountName",
        "userPrincipalName",
        "objectSid",
    ]
    search_filter = config.user_filter.format(username=escape_filter_value(username))

    with service_connection(config) as conn:
        conn.search(
            config.search_base,
            search_filter,
            search_scope=_ldap().SUBTREE,
            attributes=attributes,
        )
        if not conn.entries:
            return None, {}

        entry = conn.entries[0]
        return str(entry.entry_dn), entry_to_dict(entry)


def service_connection(config):
    if not config.service_account or not config.service_password:
        raise ImproperlyConfigured(
            "AD_SERVICE_ACCOUNT and AD_SERVICE_PASSWORD are required for LDAP search"
        )
    return ldap_connection(
        config, user=config.service_account, password=config.service_password
    )


def ldap_connection(config, *, user, password):
    ldap3 = _ldap()
    server_kwargs = {}
    if config.transport in {"starttls", "ldaps"}:
        tls_kwargs = {
            "validate": ssl.CERT_REQUIRED if config.verify_cert else ssl.CERT_NONE
        }
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
    from django.conf import settings
    from apps.accounts.services import sync_external_user_from_attributes

    profile_updates = {}
    email = attributes.get("mail")
    email_domain = getattr(settings, "AD_EMAIL_DOMAIN_OVERRIDE", None)

    if email:
        profile_updates["email"] = email
    elif email_domain:
        sam_account_name = attributes.get("sAMAccountName", "")
        if sam_account_name:
            profile_updates["email"] = f"{sam_account_name}{email_domain}"

    # Sync organizational structure (OU and Department)
    # Host-specific OU synchronization belongs in a deployment silo.
    # Uncomment and use a private LDAP backend for AD OU synchronization.
    # member_of = attributes.get("memberOf", [])
    # if member_of:
    #     from apps.core.models import OrganizationalUnit
    #     # Находим OU пользователя на основе групп
    #     for group_dn in member_of:
    #         # Извлекаем OU из DN группы
    #         ou_dn = _extract_ou_from_dn(group_dn)
    #         if ou_dn:
    #             # Находим OU в базе
    #             ou = OrganizationalUnit.objects.filter(distinguished_name=ou_dn).first()
    #             if ou:
    #                 user.organizational_unit = ou
    #
    #                 # Находим соответствующий Department (уровень 3 или выше)
    #                 dept = _find_department_for_ou(ou)
    #                 if dept:
    #                     user.department = dept
    #                 break  # Используем первую найденную группу с OU

    # Sync names
    display_name = attributes.get("displayName", "")
    given_name = attributes.get("givenName", "")
    surname = attributes.get("sn", "")

    if given_name or surname:
        profile_updates["first_name"] = given_name
        profile_updates["last_name"] = surname
    elif display_name:
        profile_updates["first_name"] = display_name

    sync_identity = bool(
        getattr(settings, "ACCOUNTS_AD_LINK_ENABLED", True)
        and getattr(settings, "ACCOUNTS_AD_LINK_MODE", "manual") == "automatic"
    )
    synced_user = sync_external_user_from_attributes(
        user=user,
        profile_updates=profile_updates,
        attributes=attributes,
        domain=getattr(settings, "AD_LDAP_DOMAIN", ""),
        sync_identity=sync_identity,
        audit_callback=record_external_directory_sync_audit,
    )
    if not synced_user.is_active:
        return synced_user
    sync_user_groups(synced_user, attributes.get("memberOf", []), group_role_map)
    return synced_user


def _extract_ou_from_dn(dn):
    """Извлекает distinguished name OU из DN группы"""
    # Пример: CN=Группа,OU=Отдел,OU=Подразделение,DC=domain,DC=local
    # Нужно найти OU компонент и всё что выше него
    parts = dn.split(",")
    ou_parts = []

    for part in reversed(parts):
        if part.startswith("OU="):
            ou_name = part[3:]
            ou_parts.insert(0, ou_name)
        elif part.startswith("DC="):
            break

    if ou_parts:
        # Формируем DN OU
        dc_parts = [part for part in parts if part.startswith("DC=")]
        return ",".join(["OU=" + ou for ou in ou_parts] + dc_parts)
    return None


def _find_department_for_ou(ou):
    """Находит соответствующий Department для OU"""
    if not ou:
        return None

    # Если OU уровня 3 или выше, ищем Department на основе name
    if ou.level >= 3:
        dept = Department.objects.filter(name=ou.name).first()
        return dept
    # Если OU уровня 2, используем его как Department
    elif ou.level == 2:
        dept = dept = Department.objects.filter(name=ou.name).first()
        return dept

    return None


def sync_user_groups(user, member_of, group_role_map):
    from django.conf import settings

    if not getattr(settings, "ACCOUNTS_AD_GROUP_ROLE_SYNC", False):
        return

    if not group_role_map:
        return

    try:
        mapped_role_names = _validated_ad_role_names(group_role_map)
    except Exception as exc:
        logger.error("AD role sync skipped because its mapping is unsafe: %s", exc)
        return

    # The current assignment service requires a human actor and an interactive
    # preview/apply authorization flow. It has no supported system-actor semantics
    # for AD. A direct M2M update here would therefore be an unaudited access write.
    # Keep authentication/profile synchronization working, but fail closed for role
    # membership until an audited AD assignment service is available.
    logger.error(
        "AD role sync is enabled for user_id=%s but role changes were skipped: "
        "an audited AD assignment service is not available (validated roles: %s).",
        user.pk,
        ", ".join(mapped_role_names),
    )


def _validated_ad_role_names(group_role_map):
    from apps.accounts.selectors import contract_role_configs

    if not isinstance(group_role_map, dict):
        raise ImproperlyConfigured("AD_GROUP_ROLE_MAP must be a mapping")

    mapped_role_names = set()
    for role_name in group_role_map.values():
        if not isinstance(role_name, str) or not role_name or role_name.startswith("$"):
            raise ImproperlyConfigured(
                "AD_GROUP_ROLE_MAP contains an invalid contract role identifier"
            )
        mapped_role_names.add(role_name)

    contract_role_names = set(contract_role_configs())
    unknown_role_names = sorted(mapped_role_names - contract_role_names)
    if unknown_role_names:
        raise ImproperlyConfigured(
            "AD_GROUP_ROLE_MAP references unknown contract roles: "
            + ", ".join(unknown_role_names)
        )

    existing_role_names = set(
        Group.objects.filter(name__in=mapped_role_names).values_list("name", flat=True)
    )
    missing_role_names = sorted(mapped_role_names - existing_role_names)
    if missing_role_names:
        raise ImproperlyConfigured(
            "AD_GROUP_ROLE_MAP references contract groups that are not seeded: "
            + ", ".join(missing_role_names)
        )

    return sorted(mapped_role_names)


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
        raise ImproperlyConfigured(
            "LDAP auth requires ldap3. Install requirements.txt first."
        ) from exc
    return ldap3


def _ldap_escape_filter_chars():
    try:
        from ldap3.utils.conv import escape_filter_chars
    except ImportError as exc:
        raise ImproperlyConfigured(
            "LDAP auth requires ldap3. Install requirements.txt first."
        ) from exc
    return escape_filter_chars
