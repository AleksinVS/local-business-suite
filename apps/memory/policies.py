from dataclasses import dataclass

from django.conf import settings

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
    if not getattr(user, "is_authenticated", False):
        return set()
    tokens = {PUBLIC_SCOPE_TOKEN, f"user:{user.id}"}
    tokens.update(f"role:{name}" for name in user.groups.values_list("name", flat=True))
    if getattr(user, "is_superuser", False):
        tokens.add("role:superuser")
    return tokens


def can_manage_memory(user) -> bool:
    return bool(getattr(user, "is_authenticated", False) and getattr(user, "is_staff", False))


def has_memory_review_capability(user, capability: str) -> bool:
    if capability not in MEMORY_REVIEW_CAPABILITIES:
        return False
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    if user.has_perm(f"memory.{capability}"):
        return True
    group_names = set(user.groups.values_list("name", flat=True))
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
    if getattr(user, "is_superuser", False):
        return True
    if not getattr(user, "is_authenticated", False):
        return False
    return scope_tokens_match(search_document_scope_tokens(document), user_scope_tokens(user))


def can_review_scoped_issue(user, issue) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(issue, "source_object_id", None):
        required_tokens = (issue.source_object.metadata or {}).get("scope_tokens") or []
    else:
        required_tokens = source_scope_tokens(getattr(issue, "source", None))
    return scope_tokens_match(required_tokens, user_scope_tokens(user))


def can_write_personal_memory(user, owner) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return bool(getattr(user, "is_superuser", False) or user.pk == getattr(owner, "pk", None))


def can_write_organization_memory(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return _user_has_role_flag(user, "memory_organization_write")


def can_review_organization_memory(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return _user_has_role_flag(user, "memory_organization_review")


def scope_tokens_match(required_tokens, allowed_tokens) -> bool:
    if not required_tokens:
        return False
    return bool(set(required_tokens) & set(allowed_tokens))


def can_access_search_document(user, document: MemorySearchDocument) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    return document.index_status == MemorySearchDocument.IndexStatus.READY and scope_tokens_match(
        search_document_scope_tokens(document),
        user_scope_tokens(user),
    )


def can_access_knowledge_item(user, item) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    if not getattr(user, "is_authenticated", False):
        return False
    if item.status != "active":
        return False
    return scope_tokens_match(item.scope_tokens, user_scope_tokens(user))


def effective_source_trust(source: MemorySource | None) -> SourceTrustDecision:
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

    defaults = _trust_defaults_for_source_kind(source.source_kind)
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


def source_allows_direct_context(source: MemorySource | None, context_kind: str = "") -> bool:
    decision = effective_source_trust(source)
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
    role_rules = getattr(settings, "LOCAL_BUSINESS_ROLE_RULES", {}) or {}
    role_names = set(user.groups.values_list("name", flat=True))
    return any(bool((role_rules.get(role_name) or {}).get(flag)) for role_name in role_names)


def _trust_defaults_for_source_kind(source_kind: str) -> dict:
    payload = getattr(settings, "LOCAL_BUSINESS_MEMORY_TRUST_POLICY", {}) or {}
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
