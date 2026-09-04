from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import islice
from typing import Any, Iterable, Mapping, Protocol, runtime_checkable

from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.views import View


AUTOCOMPLETE_RESULT_LIMIT = 20
AUTOCOMPLETE_QUERY_MAX_LENGTH = 100
AUTOCOMPLETE_CONTEXT_VALUE_MAX_LENGTH = 200
AUTOCOMPLETE_MODES = frozenset({"entity", "suggestion"})

_CODE_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,79}$")
_CONTEXT_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_RESERVED_RESULT_KEYS = {"value", "id", "label", "secondary", "metadata"}


@dataclass(frozen=True)
class AutocompleteOption:
    value: str | int
    label: str
    secondary: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        value = str(self.value).strip()[:240]
        label = str(self.label or "").strip()[:500]
        if not value or not label:
            raise ValidationError("Вариант автодополнения должен содержать value и label.")
        metadata = dict(self.metadata or {})
        result = {
            "value": value,
            # Temporary compatibility alias for clients migrated from the
            # original workorders-only endpoint.
            "id": self.value,
            "label": label,
            "secondary": str(self.secondary or "").strip()[:500],
            "metadata": metadata,
        }
        # Existing domain clients used a few explicit top-level attributes.
        # Only provider-owned, identifier-shaped keys may be mirrored, and
        # they can never override the shared response contract.
        for key, item in metadata.items():
            if (
                isinstance(key, str)
                and _CONTEXT_KEY_RE.fullmatch(key)
                and key not in _RESERVED_RESULT_KEYS
            ):
                result[key] = item
        return result


@runtime_checkable
class AutocompleteProvider(Protocol):
    code: str
    mode: str
    context_keys: tuple[str, ...]
    result_limit: int

    def can_use(self, user: Any) -> bool:
        """Return whether the current user may query this provider."""

    def search(
        self,
        *,
        user: Any,
        query: str,
        context: Mapping[str, str],
        limit: int,
    ) -> Iterable[AutocompleteOption]:
        """Return already access-scoped domain options."""


_PROVIDERS: dict[str, AutocompleteProvider] = {}


def register_autocomplete_provider(
    provider: AutocompleteProvider,
    *,
    replace: bool = False,
) -> AutocompleteProvider:
    code = _normalize_code(getattr(provider, "code", ""))
    mode = str(getattr(provider, "mode", "")).strip()
    if mode not in AUTOCOMPLETE_MODES:
        raise ValidationError("Поставщик автодополнения должен объявить режим entity или suggestion.")

    context_keys = tuple(getattr(provider, "context_keys", ()) or ())
    if len(context_keys) != len(set(context_keys)):
        raise ValidationError("Контекстные параметры автодополнения не должны повторяться.")
    for key in context_keys:
        if not isinstance(key, str) or not _CONTEXT_KEY_RE.fullmatch(key):
            raise ValidationError("Некорректное имя контекстного параметра автодополнения.")

    result_limit = int(getattr(provider, "result_limit", AUTOCOMPLETE_RESULT_LIMIT))
    if not 1 <= result_limit <= AUTOCOMPLETE_RESULT_LIMIT:
        raise ValidationError("Лимит поставщика автодополнения должен быть от 1 до 20.")
    if code in _PROVIDERS and not replace:
        raise ValidationError(f"Поставщик автодополнения '{code}' уже зарегистрирован.")
    _PROVIDERS[code] = provider
    return provider


def unregister_autocomplete_provider(code: str) -> None:
    _PROVIDERS.pop(_normalize_code(code), None)


def get_autocomplete_provider(code: str) -> AutocompleteProvider | None:
    return _PROVIDERS.get(_normalize_code(code))


def registered_autocomplete_providers() -> dict[str, AutocompleteProvider]:
    return dict(_PROVIDERS)


class AutocompleteView(View):
    """Safe transport for an explicitly registered, domain-owned provider."""

    provider_code = ""

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        if not request.user.is_authenticated:
            response = JsonResponse({"error": "Требуется вход в систему."}, status=401)
            return _private_no_store(response)

        try:
            provider = get_autocomplete_provider(self.provider_code)
        except ValidationError:
            provider = None
        if provider is None:
            response = JsonResponse({"error": "Неизвестный справочник."}, status=404)
            return _private_no_store(response)
        if not provider.can_use(request.user):
            response = JsonResponse({"error": "Доступ запрещён."}, status=403)
            return _private_no_store(response)

        query = request.GET.get("q", "").strip()[:AUTOCOMPLETE_QUERY_MAX_LENGTH]
        context = {
            key: request.GET.get(key, "").strip()[:AUTOCOMPLETE_CONTEXT_VALUE_MAX_LENGTH]
            for key in provider.context_keys
        }
        requested_limit = _positive_int(request.GET.get("limit"))
        provider_limit = max(
            1,
            min(int(provider.result_limit), AUTOCOMPLETE_RESULT_LIMIT),
        )
        limit = min(requested_limit or provider_limit, provider_limit)
        options = list(
            islice(
                provider.search(
                    user=request.user,
                    query=query,
                    context=context,
                    limit=limit,
                ),
                limit,
            )
        )
        response = JsonResponse(
            {
                "provider": provider.code,
                "mode": provider.mode,
                "results": [option.as_dict() for option in options],
            }
        )
        return _private_no_store(response)


def _normalize_code(value: Any) -> str:
    normalized = str(value or "").strip()
    if not _CODE_RE.fullmatch(normalized):
        raise ValidationError("Некорректный код поставщика автодополнения.")
    return normalized


def _positive_int(value: Any) -> int | None:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _private_no_store(response: JsonResponse) -> JsonResponse:
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Pragma"] = "no-cache"
    return response


@dataclass(frozen=True)
class DepartmentParentAutocompleteProvider:
    """Actor-scoped parent choices for the department management form."""

    code: str = "core.departments"
    mode: str = "entity"
    context_keys: tuple[str, ...] = ("current_department",)
    result_limit: int = 20

    def can_use(self, user: Any) -> bool:
        from apps.workorders.policies import can_manage_departments

        return can_manage_departments(user)

    def search(
        self,
        *,
        user: Any,
        query: str,
        context: Mapping[str, str],
        limit: int,
    ) -> Iterable[AutocompleteOption]:
        from apps.workorders.selectors import visible_departments_queryset

        current_id = _positive_int(context.get("current_department"))
        excluded_ids: set[int] = set()
        if current_id:
            from apps.core.models import Department

            current = Department.objects.filter(pk=current_id).first()
            if current is not None:
                excluded_ids.update(current.descendant_ids())
        departments = visible_departments_queryset(user).exclude(pk__in=excluded_ids)
        if query:
            departments = departments.filter(name__icontains=query)
        return [
            AutocompleteOption(value=department.pk, label=department.indented_name)
            for department in departments.select_related("parent").order_by(
                "parent_id", "name", "pk"
            )[:limit]
        ]


def register_domain_autocomplete_providers() -> None:
    register_autocomplete_provider(DepartmentParentAutocompleteProvider(), replace=True)
