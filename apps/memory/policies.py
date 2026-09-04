from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist

from .models import MemorySearchDocument, MemorySource

PUBLIC_SCOPE_TOKEN = "org:default"
TRUSTED_STATUS = "trusted"
REVIEW_REQUIRED_STATUS = "review_required"
BLOCKED_STATUS = "blocked"
MEMORY_REVIEW_CAPABILITIES = {
    "view_review_queue",
    "review_issues",
    "review_privacy_issues",
    "manage_search_index",
    "view_memory_access_audit",
}
MEMORY_REVIEW_GROUP_CAPABILITIES = {
    "memory_admin": MEMORY_REVIEW_CAPABILITIES,
    "memory_auditor": {"view_review_queue", "review_issues", "review_privacy_issues", "view_memory_access_audit"},
    "memory_index_operator": {"view_review_queue", "manage_search_index"},
    "memory_observer": {"view_review_queue"},
}
# Понятные названия и комментарии групп памяти для нетехнических пользователей;
# синхронизируются в GroupProfile командой seed_roles (ADR-0034).
MEMORY_REVIEW_GROUP_PROFILES = {
    "memory_admin": (
        "Администратор памяти",
        "Полный доступ к обслуживанию памяти ИИ: очередь ревью, проблемы приватности, поисковый индекс и аудит доступа.",
    ),
    "memory_auditor": (
        "Аудитор памяти",
        "Проверяет очередь ревью памяти ИИ, включая проблемы приватности, и просматривает аудит доступа. Не управляет поисковым индексом.",
    ),
    "memory_index_operator": (
        "Оператор индекса памяти",
        "Обслуживает поисковый индекс памяти ИИ и видит очередь ревью. Не работает с проблемами приватности.",
    ),
    "memory_observer": (
        "Наблюдатель памяти",
        "Только просмотр очереди ревью памяти ИИ, без права принимать решения.",
    ),
}
LEGACY_TRUST_STATUS_MAPPING = {
    "trusted": TRUSTED_STATUS,
    "candidate_only": REVIEW_REQUIRED_STATUS,
    "quarantined": REVIEW_REQUIRED_STATUS,
    "review_required": REVIEW_REQUIRED_STATUS,
    "blocked": BLOCKED_STATUS,
}


@dataclass(frozen=True)
class SourceTrustDecision:
    trust_status: str
    raw_trust_status: str
    authority_class: str
    trusted_for_context: bool
    requires_source_review: bool
    review_owner: str
    trusted_context_kinds: tuple[str, ...]
    untrusted_handling: str
    source_code: str = ""
    source_kind: str = ""

    @property
    def direct_context_allowed(self) -> bool:
        return self.trust_status == TRUSTED_STATUS and self.trusted_for_context


def user_scope_tokens(user):
    actor = resolve_active_actor(user)
    if actor is None:
        return set()
    tokens = {PUBLIC_SCOPE_TOKEN, f"user:{actor.id}"}
    tokens.update(scope_token_for_group_name(name) for name in actor_group_names(actor))
    if getattr(actor, "is_superuser", False):
        tokens.add("role:superuser")
    return tokens


def is_active_actor(user, *, force_refresh: bool = False) -> bool:
    """Return whether a real, persisted, active account may act.

    ``is_authenticated`` is a request-state marker, not an authorization
    decision: an inactive user and an unsaved user object must both fail
    closed.  Keeping this check in the memory policy module makes direct
    service calls and HTTP views use the same rule.
    """
    return resolve_active_actor(user, force_refresh=force_refresh) is not None


def resolve_active_actor(user, *, force_refresh: bool = False):
    """Resolve one bounded, group-prefetched active actor snapshot.

    A request may carry a stale ``User`` instance after an admin revokes a
    group or deactivates the account.  Read policies must consult the current
    row, while selectors can pass this marked snapshot through a complete
    query operation to avoid one database lookup per object.
    """
    if not force_refresh and getattr(user, "_memory_active_actor_snapshot", False):
        return user if getattr(user, "is_active", False) else None
    if not getattr(user, "is_authenticated", False) or not getattr(user, "pk", None):
        return None
    actor = (
        get_user_model().objects.filter(pk=user.pk, is_active=True)
        .prefetch_related("groups")
        .first()
    )
    if actor is not None:
        actor._memory_active_actor_snapshot = True
    return actor


def role_codes_snapshot(rules_snapshot=None) -> set[str]:
    """Return only real role names from the current role-rules snapshot."""
    if not isinstance(rules_snapshot, dict):
        from apps.core.contract_store import get_contract

        try:
            rules_snapshot = get_contract("role_rules")
        except Exception:
            return set()
    return {
        name
        for name, config in rules_snapshot.items()
        if isinstance(name, str) and not name.startswith("$") and isinstance(config, dict)
    }


def scope_token_for_group_name(name: str, rules_snapshot=None) -> str:
    """Map contract roles to ``role:`` and technical AD/Django groups to ``group:``."""
    normalized = str(name or "").strip()
    if not normalized:
        return ""
    prefix = "role:" if normalized in role_codes_snapshot(rules_snapshot) else "group:"
    return prefix + normalized


def actor_group_names(actor) -> tuple[str, ...]:
    prefetched = getattr(actor, "_prefetched_objects_cache", {}).get("groups")
    if prefetched is not None:
        return tuple(group.name for group in prefetched)
    return tuple(actor.groups.values_list("name", flat=True))


def can_manage_memory(user) -> bool:
    actor = resolve_active_actor(user, force_refresh=True)
    if actor is None:
        return False
    if getattr(actor, "is_superuser", False):
        return True
    return "memory_admin" in set(actor_group_names(actor))


def has_memory_review_capability(user, capability: str) -> bool:
    if capability not in MEMORY_REVIEW_CAPABILITIES:
        return False
    actor = resolve_active_actor(user, force_refresh=True)
    if actor is None:
        return False
    if getattr(actor, "is_superuser", False):
        return True
    group_names = set(actor_group_names(actor))
    return any(capability in MEMORY_REVIEW_GROUP_CAPABILITIES.get(group_name, set()) for group_name in group_names)


def can_view_memory_review_queue(user) -> bool:
    return has_memory_review_capability(user, "view_review_queue")


def can_review_memory_issues(user) -> bool:
    return has_memory_review_capability(user, "review_issues")


def can_review_memory_privacy_issues(user) -> bool:
    return has_memory_review_capability(user, "review_privacy_issues")


def can_manage_memory_search_index(user) -> bool:
    return has_memory_review_capability(user, "manage_search_index")


def can_view_memory_access_audit(user) -> bool:
    return has_memory_review_capability(user, "view_memory_access_audit")


def can_review_scoped_search_document(user, document: MemorySearchDocument) -> bool:
    actor = resolve_active_actor(user, force_refresh=True)
    if actor is None:
        return False
    if document.source_object_id:
        source = MemorySource.objects.filter(pk=document.source_object.source_id).first()
        if source is None or source.status != MemorySource.Status.ENABLED:
            return False
        from .services import can_access_source_object

        if not can_access_source_object(actor, document.source_object):
            return False
    if getattr(actor, "is_superuser", False):
        return True
    return scope_tokens_match(search_document_scope_tokens(document), user_scope_tokens(actor))


def can_review_scoped_issue(user, issue) -> bool:
    actor = resolve_active_actor(user, force_refresh=True)
    if actor is None:
        return False
    if not issue_source_is_consistent(issue):
        return False
    source = MemorySource.objects.filter(pk=issue.source_id).first()
    if source is None or source.status != MemorySource.Status.ENABLED:
        return False
    if getattr(issue, "source_object_id", None):
        from .services import can_access_source_object

        if not can_access_source_object(actor, issue.source_object):
            return False
        required_tokens = source_object_scope_tokens(issue.source_object, source=source)
    else:
        required_tokens = source_scope_tokens(source)
    if getattr(actor, "is_superuser", False):
        return True
    return scope_tokens_match(required_tokens, user_scope_tokens(actor))


def can_write_personal_memory(user, owner) -> bool:
    actor = resolve_active_actor(user, force_refresh=True)
    if actor is None:
        return False
    return bool(getattr(actor, "is_superuser", False) or actor.pk == getattr(owner, "pk", None))


def can_write_organization_memory(user) -> bool:
    actor = resolve_active_actor(user, force_refresh=True)
    if actor is None:
        return False
    if getattr(actor, "is_superuser", False):
        return True
    return _user_has_role_flag(actor, "memory_organization_write")


def can_review_organization_memory(user) -> bool:
    actor = resolve_active_actor(user, force_refresh=True)
    if actor is None:
        return False
    if getattr(actor, "is_superuser", False):
        return True
    return bool(
        _user_has_role_flag(actor, "memory_organization_review")
        and has_memory_review_capability(actor, "review_issues")
    )


def scope_tokens_match(required_tokens, allowed_tokens) -> bool:
    if not required_tokens:
        return False
    return bool(set(required_tokens) & set(allowed_tokens))


def can_access_search_document(user, document: MemorySearchDocument, *, snapshots=None, profile=None) -> bool:
    actor = resolve_active_actor(user, force_refresh=True)
    if actor is None:
        return False
    if document.source_object_id:
        source = MemorySource.objects.filter(pk=document.source_object.source_id).first()
        if source is None or source.status != MemorySource.Status.ENABLED:
            return False
        from .services import can_access_source_object

        if not can_access_source_object(
            actor,
            document.source_object,
            snapshots=snapshots,
            profile=profile,
        ):
            return False
    if getattr(actor, "is_superuser", False):
        return True
    return document.index_status == MemorySearchDocument.IndexStatus.READY and scope_tokens_match(
        search_document_scope_tokens(document),
        user_scope_tokens(actor),
    )


def can_access_knowledge_item(user, item) -> bool:
    actor = resolve_active_actor(user, force_refresh=True)
    if actor is None:
        return False
    if getattr(actor, "is_superuser", False):
        return True
    if item.status != "active":
        return False
    return scope_tokens_match(item.scope_tokens, user_scope_tokens(actor))


def source_object_scope_tokens(
    source_object,
    *,
    source=None,
    snapshots=None,
    profile=None,
) -> list[str]:
    source = source or getattr(source_object, "source", None)
    metadata = source_object.metadata or {}
    acl = metadata.get("acl") or {}
    acl_status = str(acl.get("status") or "").strip().lower()
    if acl_status in {"unresolved", "blocked", "unreadable", "disabled"}:
        legacy_profile_policy = ""
        if not acl.get("unresolved_policy") and profile is None and snapshots is not None:
            # A caller that already captured the operation snapshot may opt in
            # to resolving legacy objects against that exact profile.  Without
            # an explicit snapshot/profile this path remains fail-closed and
            # never performs a repository read per object.
            from .document_ingestion import get_source_ingestion_profile

            profile = get_source_ingestion_profile(source, snapshots=snapshots)
        if not acl.get("unresolved_policy") and profile is None and snapshots is None:
            # Legacy test fixtures may explicitly override the old payload
            # attribute.  Resolve that fixture without touching the repository;
            # production objects without persisted policy remain blocked.
            from .config_documents import get_memory_test_override_payload

            test_payload = get_memory_test_override_payload(
                "memory.contract.ingestion_profiles"
            ) or {}
            source_config = getattr(source, "config", {}) or {}
            profile_id = (
                source_config.get("ingestion_profile")
                or (source_config.get("ingestion") or {}).get("profile")
                or "corporate_docs_windows_v1"
            )
            configured_profile = (test_payload.get("profiles") or {}).get(profile_id) or {}
            legacy_profile_policy = (
                configured_profile.get("acl_policy") or {}
            ).get("unresolved_policy", "")
        if profile is not None:
            legacy_profile_policy = profile.unresolved_acl_policy
        unresolved_policy = (
            acl.get("unresolved_policy")
            or (getattr(source, "config", {}) or {}).get("acl_policy", {}).get("unresolved_policy")
            or legacy_profile_policy
            or "block"
        )
        if unresolved_policy in {"admin_only", "root_only"}:
            return ["role:superuser"]
        if unresolved_policy == "fallback_scope_rule":
            return source_scope_tokens(source)
        return []
    tokens = [
        str(token).strip()
        for token in (metadata.get("scope_tokens") or acl.get("scope_tokens") or [])
        if str(token).strip()
    ]
    return tokens or source_scope_tokens(source)


def can_access_source_object_scope(user, source_object, *, snapshots=None, profile=None) -> bool:
    actor = resolve_active_actor(user, force_refresh=True)
    if actor is None or source_object is None or not getattr(source_object, "source_id", None):
        return False
    # Never trust the source relation cached on the object, and never let the
    # root shortcut skip the lifecycle fence.
    source = MemorySource.objects.filter(pk=source_object.source_id).first()
    if source is None or source.status != MemorySource.Status.ENABLED:
        return False
    required = source_object_scope_tokens(
        source_object,
        source=source,
        snapshots=snapshots,
        profile=profile,
    )
    if not required:
        return False
    if not getattr(actor, "is_superuser", False) and not scope_tokens_match(required, user_scope_tokens(actor)):
        return False
    return True


def issue_source_is_consistent(issue) -> bool:
    """Reject an issue whose denormalized source disagrees with its target."""
    if not getattr(issue, "source_id", None):
        return False
    if not getattr(issue, "source_object_id", None):
        return True
    try:
        source_object = getattr(issue, "source_object", None)
    except ObjectDoesNotExist:
        return False
    return source_object is not None and source_object.source_id == issue.source_id


def effective_source_trust(source: MemorySource | None, *, snapshots=None) -> SourceTrustDecision:
    if source is None:
        return SourceTrustDecision(
            trust_status=REVIEW_REQUIRED_STATUS,
            raw_trust_status="candidate_only",
            authority_class="candidate_input",
            trusted_for_context=False,
            requires_source_review=True,
            review_owner="knowledge_owner",
            trusted_context_kinds=(),
            untrusted_handling=REVIEW_REQUIRED_STATUS,
        )

    defaults = _trust_defaults_for_source_kind(source.source_kind, snapshots=snapshots)
    raw_trust_status = source.trust_status or defaults.get("trust_status", REVIEW_REQUIRED_STATUS)
    trust_status = normalize_trust_status(raw_trust_status)
    authority_class = source.authority_class or defaults.get("authority_class", "candidate_input")
    trusted_for_context = (
        bool(source.trusted_for_context)
        if source.trust_status or source.authority_class
        else bool(defaults.get("trusted_for_context", False))
    )
    requires_source_review = (
        bool(source.requires_source_review)
        if source.trust_status or source.authority_class
        else bool(defaults.get("requires_source_review", True))
    )
    review_owner = source.review_owner or defaults.get("review_owner", "knowledge_owner")
    context_kinds = source.trusted_context_kinds or defaults.get("trusted_context_kinds", ())
    return SourceTrustDecision(
        trust_status=trust_status,
        raw_trust_status=raw_trust_status,
        authority_class=authority_class,
        trusted_for_context=trusted_for_context,
        requires_source_review=requires_source_review,
        review_owner=review_owner,
        trusted_context_kinds=tuple(context_kinds or ()),
        untrusted_handling=normalize_untrusted_handling(
            source.untrusted_handling or defaults.get("untrusted_handling", REVIEW_REQUIRED_STATUS)
        ),
        source_code=source.code,
        source_kind=source.source_kind,
    )


def source_allows_direct_context(source: MemorySource | None, context_kind: str = "", *, snapshots=None) -> bool:
    decision = effective_source_trust(source, snapshots=snapshots)
    if not decision.direct_context_allowed:
        return False
    if context_kind and decision.trusted_context_kinds:
        return context_kind in decision.trusted_context_kinds
    return True


def search_document_scope_tokens(document: MemorySearchDocument) -> list[str]:
    if document.corpus_type == MemorySearchDocument.CorpusType.KNOWLEDGE and document.knowledge_item_id:
        return list(document.knowledge_item.scope_tokens or [])
    if document.source_object_id:
        return list((document.source_object.metadata or {}).get("scope_tokens") or [])
    return []


def source_scope_tokens(source: MemorySource | None) -> list[str]:
    if source is None:
        return []
    from .acl import scope_tokens_for_source_scope_rule

    return list(scope_tokens_for_source_scope_rule(source))


def search_document_sensitivity(document: MemorySearchDocument) -> str:
    if document.corpus_type == MemorySearchDocument.CorpusType.KNOWLEDGE and document.knowledge_item_id:
        return document.knowledge_item.sensitivity
    if document.source_object_id and document.source_object.source_id:
        return document.source_object.source.sensitivity
    return ""


def search_document_source(document: MemorySearchDocument) -> MemorySource | None:
    if document.corpus_type == MemorySearchDocument.CorpusType.KNOWLEDGE and document.knowledge_item_id:
        source = MemorySource.objects.filter(code=document.knowledge_item.source_code).first()
        if source is not None:
            return source
        fallback_code = (
            "ai_chat_organization"
            if document.knowledge_item.scope == "organization"
            else "ai_chat_personal"
        )
        return MemorySource.objects.filter(code=fallback_code).first()
    if document.source_object_id:
        return document.source_object.source
    return None


def _user_has_role_flag(user, flag: str) -> bool:
    from apps.core.contract_store import get_contract

    role_rules = get_contract("role_rules")
    actor = resolve_active_actor(user, force_refresh=True)
    if actor is None:
        return False
    role_names = set(actor_group_names(actor))
    return any(bool((role_rules.get(role_name) or {}).get(flag)) for role_name in role_names)


def _trust_defaults_for_source_kind(source_kind: str, *, snapshots=None) -> dict:
    from .config_documents import get_memory_document_payload

    payload = get_memory_document_payload(
        "memory.contract.trust_policy", snapshots=snapshots
    ) or {}
    defaults = payload.get("defaults_by_source_kind") or {}
    return dict(defaults.get(source_kind) or defaults.get("*") or {})


def normalize_trust_status(value: str) -> str:
    return LEGACY_TRUST_STATUS_MAPPING.get(str(value or "").strip(), REVIEW_REQUIRED_STATUS)


def normalize_untrusted_handling(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized in {"candidate_only", "quarantine"}:
        return REVIEW_REQUIRED_STATUS
    if normalized == "block":
        return BLOCKED_STATUS
    if normalized in {REVIEW_REQUIRED_STATUS, BLOCKED_STATUS}:
        return normalized
    return REVIEW_REQUIRED_STATUS
