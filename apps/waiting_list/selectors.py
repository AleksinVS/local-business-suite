from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.workorders.policies import active_role_rules

from .models import WaitingListEntry


def waiting_list_view_scope(rule: dict) -> str:
    """Return the explicit scope or the narrow rollout fallback for legacy rules."""

    if "waiting_list_view_scope" in rule:
        value = rule.get("waiting_list_view_scope")
        return value if value in {"none", "authored", "all"} else "none"
    return "all" if rule.get("view_waiting_list") is True else "none"


def visible_waiting_list_entries(
    actor,
    *,
    queryset: QuerySet | None = None,
    rules_payload: dict | None = None,
) -> QuerySet:
    """Canonical PII-safe queryset for every interactive waiting-list reader."""

    queryset = queryset if queryset is not None else WaitingListEntry.objects.all()
    if not getattr(actor, "is_authenticated", False) or not getattr(actor, "is_active", False):
        return queryset.none()

    scopes = {
        waiting_list_view_scope(rule)
        for rule in active_role_rules(actor, rules_payload=rules_payload)
    }
    if "all" in scopes:
        return queryset
    visibility = Q(pk__in=[])
    if "authored" in scopes and getattr(actor, "pk", None):
        visibility |= Q(author_id=actor.pk)
    return queryset.filter(visibility)
