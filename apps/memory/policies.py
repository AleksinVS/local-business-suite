from django.conf import settings

from .models import MemoryChunk, MemoryGraphFact

PUBLIC_SCOPE_TOKEN = "org:default"


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


def can_access_chunk(user, chunk: MemoryChunk) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    return chunk.is_active and scope_tokens_match(chunk.scope_tokens, user_scope_tokens(user))


def can_access_graph_fact(user, fact: MemoryGraphFact) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    return fact.is_active and scope_tokens_match(fact.scope_tokens, user_scope_tokens(user))


def _user_has_role_flag(user, flag: str) -> bool:
    role_rules = getattr(settings, "LOCAL_BUSINESS_ROLE_RULES", {}) or {}
    role_names = set(user.groups.values_list("name", flat=True))
    return any(bool((role_rules.get(role_name) or {}).get(flag)) for role_name in role_names)
