from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from urllib.parse import unquote, urlsplit

from django.core.exceptions import PermissionDenied, ValidationError


DEFAULT_RIGHT_PANEL_TARGET = "#global-right-panel-content"
DEFAULT_RIGHT_PANEL_SWAP = "innerHTML"
DEFAULT_RIGHT_PANEL_MODE = "view"
RIGHT_PANEL_COMMAND_OPEN = "open_right_panel"
RIGHT_PANEL_FORM_COMMAND_OPEN = "open_right_panel_form"
RIGHT_PANEL_FORM_MODES = frozenset({"create", "edit"})

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9_.:-]+$")
_SUPPORTED_SWAPS = {"innerHTML"}
_SUPPORTED_MODES = {DEFAULT_RIGHT_PANEL_MODE, *RIGHT_PANEL_FORM_MODES}
_SUPPORTED_DRAWER_SIZES = {"default", "large", "waiting_list", "workspace"}


@dataclass(frozen=True)
class RightPanelDescriptor:
    source_code: str
    object_type: str
    object_id: str
    title: str
    htmx_url: str
    mode: str = DEFAULT_RIGHT_PANEL_MODE
    target: str = DEFAULT_RIGHT_PANEL_TARGET
    swap: str = DEFAULT_RIGHT_PANEL_SWAP
    drawer_size: str = "default"
    context_hint: str = ""
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        normalized = {
            "source_code": _normalize_identifier(self.source_code, "source_code"),
            "object_type": _normalize_identifier(self.object_type, "object_type"),
            "object_id": _normalize_object_id(self.object_id),
            "mode": _normalize_mode(self.mode),
            "title": str(self.title or "").strip()[:200],
            "htmx_url": _normalize_local_path(self.htmx_url),
            "target": _normalize_target(self.target),
            "swap": _normalize_swap(self.swap),
            "drawer_size": _normalize_drawer_size(self.drawer_size),
            "context_hint": str(self.context_hint or "").strip()[:240],
            "metadata": dict(self.metadata or {}),
        }
        if not normalized["title"]:
            normalized["title"] = f"{normalized['source_code']} / {normalized['object_type']}#{normalized['object_id']}"
        for key, value in normalized.items():
            object.__setattr__(self, key, value)

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": RIGHT_PANEL_COMMAND_OPEN,
            "source_code": self.source_code,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "mode": self.mode,
            "title": self.title,
            "htmx_url": self.htmx_url,
            "target": self.target,
            "swap": self.swap,
            "drawer_size": self.drawer_size,
            "context_hint": self.context_hint,
            "metadata": dict(self.metadata or {}),
        }


@dataclass(frozen=True)
class RightPanelFormDescriptor:
    """Human-initiated form command backed by a registered domain provider.

    The wrapper deliberately has no URL field of its own.  A domain provider
    must resolve permissions, the object and the local HTMX endpoint first;
    callers therefore cannot turn the shared shell into arbitrary CRUD.
    """

    panel: RightPanelDescriptor

    def __post_init__(self) -> None:
        if self.panel.mode not in RIGHT_PANEL_FORM_MODES:
            raise ValidationError("Форма правой панели поддерживает только создание или редактирование.")

    def as_dict(self) -> dict[str, Any]:
        payload = self.panel.as_dict()
        payload["type"] = RIGHT_PANEL_FORM_COMMAND_OPEN
        return payload


@runtime_checkable
class RightPanelProvider(Protocol):
    source_code: str
    object_type: str
    supported_modes: tuple[str, ...]

    def can_open(self, user: Any, object_id: str, mode: str = DEFAULT_RIGHT_PANEL_MODE) -> bool:
        """Return True only when the current user may open the object in a panel."""

    def build_panel(self, user: Any, object_id: str, mode: str = DEFAULT_RIGHT_PANEL_MODE) -> RightPanelDescriptor:
        """Build a safe server-owned panel descriptor."""


_PROVIDERS: dict[tuple[str, str], RightPanelProvider] = {}


def register_right_panel_provider(provider: RightPanelProvider, *, replace: bool = False) -> RightPanelProvider:
    source_code = _normalize_identifier(getattr(provider, "source_code", ""), "source_code")
    object_type = _normalize_identifier(getattr(provider, "object_type", ""), "object_type")
    supported_modes = tuple(getattr(provider, "supported_modes", ()) or ())
    if not supported_modes:
        raise ValidationError("Поставщик правой панели должен объявить supported_modes.")
    for mode in supported_modes:
        _normalize_mode(mode)
    key = (source_code, object_type)
    if key in _PROVIDERS and not replace:
        raise ValidationError(f"Поставщик правой панели '{source_code}/{object_type}' уже зарегистрирован.")
    _PROVIDERS[key] = provider
    return provider


def unregister_right_panel_provider(source_code: str, object_type: str) -> None:
    _PROVIDERS.pop((_normalize_identifier(source_code, "source_code"), _normalize_identifier(object_type, "object_type")), None)


def get_right_panel_provider(source_code: str, object_type: str) -> RightPanelProvider | None:
    return _PROVIDERS.get((_normalize_identifier(source_code, "source_code"), _normalize_identifier(object_type, "object_type")))


def registered_right_panel_providers() -> dict[tuple[str, str], RightPanelProvider]:
    return dict(_PROVIDERS)


def clear_right_panel_providers() -> None:
    _PROVIDERS.clear()


def build_right_panel_descriptor(
    *,
    user: Any,
    source_code: str,
    object_type: str,
    object_id: str,
    mode: str = DEFAULT_RIGHT_PANEL_MODE,
) -> RightPanelDescriptor:
    normalized_source = _normalize_identifier(source_code, "source_code")
    normalized_type = _normalize_identifier(object_type, "object_type")
    normalized_mode = _normalize_mode(mode)
    normalized_object_id = _normalize_object_id(object_id)
    provider = get_right_panel_provider(normalized_source, normalized_type)
    if provider is None:
        raise ValidationError("Объект нельзя открыть в правой панели.")
    supported_modes = tuple(getattr(provider, "supported_modes", ()) or ())
    if normalized_mode not in supported_modes:
        raise ValidationError("Режим правой панели не поддерживается.")
    if not provider.can_open(user, normalized_object_id, normalized_mode):
        raise PermissionDenied("Объект недоступен для правой панели.")
    descriptor = provider.build_panel(user, normalized_object_id, normalized_mode)
    if descriptor.source_code != normalized_source or descriptor.object_type != normalized_type:
        raise ValidationError("Поставщик правой панели вернул несогласованный дескриптор.")
    if descriptor.object_id != normalized_object_id:
        raise ValidationError("Поставщик правой панели вернул несогласованный object_id.")
    if descriptor.mode != normalized_mode:
        raise ValidationError("Поставщик правой панели вернул несогласованный режим.")
    return descriptor


def build_human_right_panel_form_descriptor(
    *,
    user: Any,
    source_code: str,
    object_type: str,
    object_id: str,
    mode: str,
) -> RightPanelFormDescriptor:
    """Build a server-owned create/edit command for an explicit human action."""

    normalized_mode = _normalize_mode(mode)
    if normalized_mode not in RIGHT_PANEL_FORM_MODES:
        raise ValidationError("Пользовательская форма правой панели поддерживает только create/edit.")
    panel = build_right_panel_descriptor(
        user=user,
        source_code=source_code,
        object_type=object_type,
        object_id=object_id,
        mode=normalized_mode,
    )
    return RightPanelFormDescriptor(panel=panel)


def _normalize_identifier(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValidationError(f"Поле правой панели {field_name} не должно быть пустым.")
    if len(normalized) > 80 or not _IDENTIFIER_RE.match(normalized):
        raise ValidationError(f"Поле правой панели {field_name} некорректно.")
    return normalized


def _normalize_mode(value: Any) -> str:
    normalized = _normalize_identifier(value or DEFAULT_RIGHT_PANEL_MODE, "mode")
    if normalized not in _SUPPORTED_MODES:
        raise ValidationError("Режим правой панели не поддерживается.")
    return normalized


def _normalize_object_id(value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValidationError("object_id правой панели не должен быть пустым.")
    if len(normalized) > 120 or any(ord(ch) < 32 for ch in normalized):
        raise ValidationError("object_id правой панели некорректен.")
    return normalized


def _normalize_local_path(value: Any) -> str:
    normalized = str(value or "").strip()
    candidates = [normalized]
    for _ in range(3):
        decoded = unquote(candidates[-1])
        if decoded == candidates[-1]:
            break
        candidates.append(decoded)
    for candidate in candidates:
        try:
            parsed = urlsplit(candidate)
        except ValueError as exc:
            raise ValidationError("htmx_url правой панели должен быть безопасным локальным путем.") from exc
        if (
            not candidate.startswith("/")
            or candidate.startswith("//")
            or "\\" in candidate
            or parsed.scheme
            or parsed.netloc
            or parsed.fragment
            or not parsed.path.startswith("/")
            or parsed.path.startswith("//")
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in candidate)
        ):
            raise ValidationError("htmx_url правой панели должен быть безопасным локальным путем.")
    return normalized


def _normalize_target(value: Any) -> str:
    normalized = str(value or DEFAULT_RIGHT_PANEL_TARGET).strip()
    if normalized != DEFAULT_RIGHT_PANEL_TARGET:
        raise ValidationError("Цель правой панели не поддерживается.")
    return normalized


def _normalize_swap(value: Any) -> str:
    normalized = str(value or DEFAULT_RIGHT_PANEL_SWAP).strip()
    if normalized not in _SUPPORTED_SWAPS:
        raise ValidationError("Режим замены правой панели не поддерживается.")
    return normalized


def _normalize_drawer_size(value: Any) -> str:
    normalized = str(value or "default").strip()
    if normalized not in _SUPPORTED_DRAWER_SIZES:
        raise ValidationError("Размер правой панели не поддерживается.")
    return normalized
