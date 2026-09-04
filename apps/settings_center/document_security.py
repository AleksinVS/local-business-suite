"""Единая проверка документов настроек на встроенные секреты."""

from __future__ import annotations

import re
from typing import Any


RAW_SECRET_KEYS = frozenset(
    {
        "password",
        "api_key",
        "private_key",
        "credential",
        "access_token",
        "refresh_token",
        "client_secret",
        "secret_key",
        "token_key",
        "secret",
        "token",
    }
)
SECRET_REFERENCE_SUFFIXES = ("_env", "_ref", "_handle")
_COMPOUND_KEY_ALIASES = {
    "apikey": "api_key",
    "privatekey": "private_key",
    "accesstoken": "access_token",
    "refreshtoken": "refresh_token",
    "clientsecret": "client_secret",
    "secretkey": "secret_key",
    "tokenkey": "token_key",
}


class RawSecretValueError(ValueError):
    """Документ содержит поле, которое должно ссылаться на хранилище секретов."""


def normalize_sensitive_key(key: Any) -> str:
    """Привести snake/kebab/camel/PascalCase к одному виду."""

    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key))
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    for compact, canonical in _COMPOUND_KEY_ALIASES.items():
        if text == compact:
            return canonical
        if text.startswith(compact):
            suffix = text[len(compact) :]
            if suffix in {item.lstrip("_") for item in SECRET_REFERENCE_SUFFIXES}:
                return canonical + "_" + suffix
            if suffix in SECRET_REFERENCE_SUFFIXES or suffix in {
                "_value",
                "_raw",
                "_plaintext",
            }:
                return canonical + suffix
    return text


def _is_raw_secret_key(normalized: str) -> bool:
    if normalized in RAW_SECRET_KEYS:
        return True
    return any(
        normalized in {
            f"{secret_key}_value",
            f"{secret_key}_raw",
            f"{secret_key}_plaintext",
            f"raw_{secret_key}",
        }
        or normalized.endswith(f"_{secret_key}")
        for secret_key in RAW_SECRET_KEYS
    )


def classify_secret_references(payload: Any) -> str:
    """Вернуть ``rejected``, ``reference_only`` или ``clear`` без чтения значений."""

    reference_found = False

    def contains_raw_secret(node: Any) -> bool:
        nonlocal reference_found
        if isinstance(node, dict):
            for key, value in node.items():
                normalized = normalize_sensitive_key(key)
                if normalized.endswith(SECRET_REFERENCE_SUFFIXES) and any(
                    secret_key in normalized for secret_key in RAW_SECRET_KEYS
                ):
                    reference_found = True
                elif normalized in {"secret", "token"} and isinstance(value, dict):
                    # Объекты ``secret``/``token`` могут содержать metadata или
                    # явную ссылку. Любое value-bearing поле остаётся raw.
                    if contains_raw_secret(value):
                        return True
                    nested_keys = {
                        normalize_sensitive_key(nested_key) for nested_key in value
                    }
                    if nested_keys & {
                        "value",
                        "data",
                        "content",
                        "plaintext",
                        "raw",
                        "key",
                    }:
                        return True
                    if nested_keys & {
                        "ref",
                        "env",
                        "handle",
                        "key_ref",
                        "key_env",
                        "key_handle",
                    }:
                        reference_found = True
                elif _is_raw_secret_key(normalized):
                    return True
                if contains_raw_secret(value):
                    return True
        elif isinstance(node, list):
            return any(contains_raw_secret(value) for value in node)
        return False

    if contains_raw_secret(payload):
        return "rejected"
    return "reference_only" if reference_found else "clear"


def assert_no_raw_secrets(payload: Any) -> None:
    if classify_secret_references(payload) == "rejected":
        raise RawSecretValueError(
            "Секреты нельзя сохранять в документе настроек; используйте ссылку *_env, *_ref или *_handle."
        )
