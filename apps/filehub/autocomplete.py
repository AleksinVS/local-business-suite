"""FileHub-owned autocomplete providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from apps.core.autocomplete import AutocompleteOption, register_autocomplete_provider
from apps.memory.policies import is_active_actor

from .selectors import file_object_autocomplete_candidates


@dataclass(frozen=True)
class FileObjectAutocompleteProvider:
    code: str = "filehub.file_object"
    mode: str = "entity"
    context_keys: tuple[str, ...] = ()
    result_limit: int = 20

    def can_use(self, user) -> bool:
        return is_active_actor(user)

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        options = []
        for file_object in file_object_autocomplete_candidates(
            user,
            query=query,
            limit=limit,
        ):
            version = file_object.current_version
            source_object = getattr(version, "source_object", None)
            filename = getattr(source_object, "file_name", "") or file_object.file_id
            # The provider deliberately returns no physical/raw path. The
            # identifier is revalidated by can_access_file_object on POST.
            options.append(
                AutocompleteOption(
                    value=file_object.pk,
                    label=filename,
                    secondary=file_object.source.code,
                )
            )
            if len(options) >= limit:
                break
        return options


def register() -> None:
    register_autocomplete_provider(FileObjectAutocompleteProvider(), replace=True)
