"""Memory-review providers that preserve source and issue ACL boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from apps.core.autocomplete import AutocompleteOption, register_autocomplete_provider
from apps.workorders.selectors import resolve_active_actor

from .policies import can_view_memory_review_queue
from .review_selectors import (
    assignees_for_issue,
    issue_available_actions,
    review_issue_queryset,
    source_filter_options,
)


@dataclass(frozen=True)
class MemorySourceAutocompleteProvider:
    code: str = "memory.source"
    mode: str = "entity"
    context_keys: tuple[str, ...] = ()
    result_limit: int = 20

    def can_use(self, user) -> bool:
        actor = resolve_active_actor(user, force_refresh=True)
        return bool(actor and can_view_memory_review_queue(actor))

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        values = source_filter_options(user)
        if query:
            values = values.filter(code__icontains=query)
        return [AutocompleteOption(value=code, label=code) for code in values[:limit]]


@dataclass(frozen=True)
class MemoryIssueAssigneeAutocompleteProvider:
    code: str = "memory.issue_assignee"
    mode: str = "entity"
    context_keys: tuple[str, ...] = ("issue",)
    result_limit: int = 20

    def can_use(self, user) -> bool:
        actor = resolve_active_actor(user, force_refresh=True)
        return bool(actor and can_view_memory_review_queue(actor))

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        try:
            issue_id = int(context.get("issue") or "")
        except (TypeError, ValueError):
            return []
        issue = review_issue_queryset(user).filter(pk=issue_id).first()
        if issue is None or "assign" not in issue_available_actions(issue, user=user):
            return []
        options = []
        for assignee in assignees_for_issue(
            issue,
            actor=user,
            query=query,
            limit=limit,
        ):
            label = assignee.get_full_name() or assignee.username
            options.append(
                AutocompleteOption(
                    value=assignee.pk,
                    label=label,
                    secondary=assignee.username,
                )
            )
            if len(options) >= limit:
                break
        return options


def register() -> None:
    register_autocomplete_provider(MemorySourceAutocompleteProvider(), replace=True)
    register_autocomplete_provider(MemoryIssueAssigneeAutocompleteProvider(), replace=True)
