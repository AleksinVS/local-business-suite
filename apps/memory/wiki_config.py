"""Operator-owned wiki registry. Frontmatter cannot grant access to a bundle."""
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}\Z")
_BUNDLE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_SENSITIVITY = {"public", "internal", "confidential"}
_FIELDS = {"path", "read_tokens", "write_tokens", "note_read_tokens", "projection_user_id",
           "sensitivity", "model_context"}


@dataclass(frozen=True)
class WikiBundle:
    bundle_id: str
    path: str
    read_tokens: tuple[str, ...]
    write_tokens: tuple[str, ...] = ()
    projection_user_id: int | None = None
    sensitivity: str = "internal"
    note_read_tokens: dict = field(default_factory=dict)
    model_context: bool = False


def _tokens(values):
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not re.fullmatch(r"(org|group|role|user):[^:*\s]+", value)
        for value in values
    ):
        raise ValueError
    return tuple(values)


def wiki_bundles() -> dict[str, WikiBundle]:
    raw = getattr(settings, "LOCAL_BUSINESS_WIKI_BUNDLES", {})
    try:
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, dict):
            raise ValueError
        registry = {}
        paths = []
        for name, entry in raw.items():
            if not _BUNDLE_ID.fullmatch(name) or not isinstance(entry, dict) or set(entry) - _FIELDS:
                raise ValueError
            path = PurePosixPath(entry["path"])
            if (str(path) != entry["path"] or path.parts[:2] != ("org", "crow") or len(path.parts) < 3
                    or any(part.startswith(".") or "\\" in part or any(ord(c) < 32 for c in part)
                           for part in path.parts)
                    or any(path.is_relative_to(p) or p.is_relative_to(path) for p in paths)):
                raise ValueError
            paths.append(path)
            user_id = entry["projection_user_id"]
            sensitivity = entry.get("sensitivity", "internal")
            context = entry.get("model_context", False)
            if type(user_id) is not int or user_id < 1 or sensitivity not in _SENSITIVITY or type(context) is not bool:
                raise ValueError
            restrictions = entry.get("note_read_tokens", {})
            if not isinstance(restrictions, dict) or any(not _ID.fullmatch(k) for k in restrictions):
                raise ValueError
            registry[name] = WikiBundle(name, str(path), _tokens(entry["read_tokens"]),
                                        _tokens(entry.get("write_tokens", [])), user_id, sensitivity,
                                        {key: _tokens(values) for key, values in restrictions.items()}, context)
        return registry
    except (KeyError, TypeError, ValueError) as exc:
        raise ImproperlyConfigured("Некорректный реестр LOCAL_BUSINESS_WIKI_BUNDLES.") from exc


def wiki_article_id(bundle, metadata):
    explicit = metadata.get("knowledge_id")
    native = metadata.get("id")
    for value in (explicit, native):
        if value is not None and (not isinstance(value, str) or not _ID.fullmatch(value)):
            raise ValueError("Некорректный идентификатор Note.")
    if explicit:
        if explicit.startswith("crow:"):
            if not native or explicit != wiki_article_id(bundle, {"id": native}):
                raise ValueError("Префикс crow: зарезервирован для нативной идентичности.")
        return explicit
    if not native:
        raise ValueError("У Note отсутствует устойчивый идентификатор.")
    digest = hashlib.sha256(f"{bundle.bundle_id}\0{native}".encode()).hexdigest()
    return f"crow:{digest}"
