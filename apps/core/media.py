"""Единый защищённый media-dispatcher по префиксам первого сегмента пути.

Ядро (``apps.core``) НЕ знает о доменных моделях. Приложения сами регистрируют
политику доступа для своего префикса медиа-пути через ``register_media_policy``
в ``AppConfig.ready()``. Диспетчер ``serve_protected_media`` по первому сегменту
пути (``workorders``, ``chat_attachments`` …) выбирает политику домена и
делегирует ей проверку прав и выдачу файла.

Модуль обобщает hardening пакета 03 (отсечение null-байта, защита от path
traversal и доменная проверка прав) на произвольные префиксы и всегда отвечает
404 при отказе, не раскрывая факт существования файла (никогда 403).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from django.conf import settings
from django.http import FileResponse, Http404

# Политика домена: (request, subpath) -> FileResponse | None.
# ``subpath`` — путь ВНУТРИ префикса (без ведущего ``"<prefix>/"``).
MediaPolicy = Callable[..., Optional[FileResponse]]

# Реестр «префикс первого сегмента» -> политика. Наполняется приложениями из
# их ``AppConfig.ready()``; ядро само доменов не знает.
_REGISTRY: "dict[str, MediaPolicy]" = {}


def register_media_policy(prefix: str, policy: MediaPolicy) -> None:
    """Регистрирует политику выдачи медиа для первого сегмента пути."""
    _REGISTRY[prefix] = policy


def resolve_media_path(prefix: str, subpath: str) -> Optional[Path]:
    """Резолвит абсолютный путь к файлу внутри ``MEDIA_ROOT/<prefix>/``.

    Повторяет hardening пакета 03: отсекает null-байт (иначе ``Path.resolve()``
    падает ``ValueError`` → HTTP 500) и гарантирует, что итоговый путь лежит
    строго внутри ``MEDIA_ROOT`` (защита от path traversal ``../../``).
    Возвращает ``None`` при любой попытке выхода за пределы каталога.
    """
    if "\x00" in subpath:
        return None
    media_root = Path(settings.MEDIA_ROOT).resolve()
    absolute = (media_root / prefix / subpath).resolve()
    if not absolute.is_relative_to(media_root):
        return None
    return absolute


def build_file_response(absolute_path, filename, content_type=None) -> FileResponse:
    """Стриминговая выдача файла с заданным именем.

    ``Content-Type`` проставляется только если он передан явно; иначе тип
    выводит сам ``FileResponse`` по имени файла.
    """
    response = FileResponse(Path(absolute_path).open("rb"), filename=filename)
    if content_type:
        response["Content-Type"] = content_type
    return response


def serve_protected_media(request, path):
    """Диспетчер защищённой выдачи ``/media/<prefix>/<subpath>``.

    По первому сегменту пути выбирает зарегистрированную политику домена и
    делегирует ей проверку прав. При отсутствии политики, пустом ``subpath`` или
    отказе политики (``None``) — всегда 404, факт существования файла не
    раскрывается.
    """
    if "\x00" in path:
        raise Http404("Файл не найден")

    prefix, _, subpath = path.partition("/")
    policy = _REGISTRY.get(prefix)
    if policy is None or not subpath:
        raise Http404("Файл не найден")

    response = policy(request, subpath)
    if response is None:
        raise Http404("Файл не найден")
    return response
