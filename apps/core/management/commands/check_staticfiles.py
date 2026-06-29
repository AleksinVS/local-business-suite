"""``manage.py check_staticfiles`` — сверка ``static/src/`` и ``staticfiles/``.

Сверяет только ``*.js`` и ``*.css``: всё остальное либо генерируется
runtime-сервисами (``dist/copilotkit/`` собирается из npm), либо
загружается как медиа (``data/``).

Legacy-артефакты в ``staticfiles/`` (``.bak``, ``test_marker.txt`` и т.п.)
печатаются отдельно как «исторические следы» — намеренно, чтобы прибрать
в рамках отдельной задачи, а не молча игнорировать.

См. ADR-0029.
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


# Расширения файлов под source, которые обязаны синхронизироваться с
# ``staticfiles/``. Сознательно НЕ включаем ``html``, ``webmanifest``,
# картинки и т.п. — у них другой жизненный цикл (часть живёт только в
# ``static/src/``, часть вообще под media).
_SYNCED_EXTENSIONS = {".js", ".css"}

# Шаблоны legacy-артефактов в ``staticfiles/``, которые мы видели в
# истории (``native_ai.css.bak``, ``test_marker.txt`` и т.п.) и которые
# не имеют источника. Игнорируются при сверке, но выводятся как
# предупреждение. Можно дополнить через ``--ignore``. Шаблоны —
# shell-glob (``fnmatch``) или regex ``/pattern/``.
_DEFAULT_LEGACY_PATTERNS = (
    "*.bak",
    "test_marker.txt",
)

# Дополнительные предикаты имени файла, которые мы видели как «нормальный
# мусор» в ``staticfiles/``: артефакты ``ManifestStaticFilesStorage`` и
# сжатые копии. Они источника под ``static/src/`` не имеют и не должны.
_MANIFEST_HASH_RE = re.compile(r"^.+?\.[0-9a-f]{8}\.(?:js|css)$")
_GZIP_RE = re.compile(r"\.gz$")


class Command(BaseCommand):
    help = (
        "Проверяет, что исходники под static/src/ существуют и совпадают "
        "по размеру с собранной staticfiles/. Ловит расхождение до того, "
        "как пользователь увидит «Загрузка чата...» в проде."
    )

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--fail",
            action="store_true",
            help="Превращать любые несоответствия в CommandError (для CI).",
        )
        parser.add_argument(
            "--ignore",
            action="append",
            default=[],
            metavar="PATTERN",
            help=(
                "Шаблон legacy-артефактов в staticfiles/, которые нужно "
                "исключить из проверки. Можно передавать несколько раз."
            ),
        )

    def handle(self, *args, **options) -> None:
        static_root = self._resolve_static_root()
        static_src = _static_src_root()

        if not static_src.exists():
            self.stdout.write(
                self.style.NOTICE(f"{static_src} не существует — пропуск.")
            )
            return

        if not static_root.exists():
            self.stderr.write(
                self.style.WARNING(
                    f"{static_root} не существует. Запустите "
                    "`python manage.py collectstatic` и повторите."
                )
            )
            if options["fail"]:
                raise CommandError("staticfiles/ отсутствует — collectstatic не запускался.")
            return

        # Внутри ``static_root`` собираем пути только под ``src/`` — то самое
        # зеркало, которое соответствует ``static/src/``.
        mirror_roots = list(_mirrored_roots(static_src, static_root))
        if not mirror_roots:
            self.stderr.write(
                self.style.WARNING(
                    f"{static_root / 'src'} не существует. Запустите "
                    "`python manage.py collectstatic` и повторите."
                )
            )
            if options["fail"]:
                raise CommandError("staticfiles/src/ отсутствует — collectstatic не запускался.")
            return
        mirror_root = mirror_roots[0]
        synced = list(_walk_synced(static_src, mirror_root))
        legacy_patterns = tuple(_DEFAULT_LEGACY_PATTERNS) + tuple(options["ignore"])

        missing_in_staticfiles: list[Path] = []
        size_mismatches: list[tuple[Path, int, int]] = []
        legacy_artifacts: list[Path] = []

        for relpath, src_path, dst_path in synced:
            if not dst_path.exists():
                missing_in_staticfiles.append(relpath)
                continue
            src_size = src_path.stat().st_size
            dst_size = dst_path.stat().st_size
            if src_size != dst_size:
                size_mismatches.append((relpath, src_size, dst_size))

        seen_legacy: set[Path] = set()
        # Идём только по «нашему» зеркалу — тем же поддеревьям, что и
        # ``static/src/``. Иначе под ``staticfiles/`` ложно флагуются
        # статики ``django.contrib.admin``, ``django_htmx`` и подобные,
        # для которых в ``static/src/`` источника нет и не должно быть.
        for entry in mirror_root.rglob("*"):
            if not entry.is_file():
                continue
            if entry.suffix not in _SYNCED_EXTENSIONS:
                continue
            rel = entry.relative_to(mirror_root)
            src_candidate = static_src.joinpath(rel)
            if src_candidate.exists():
                continue
            if _matches_any(rel, legacy_patterns):
                continue
            if rel in seen_legacy:
                continue
            seen_legacy.add(rel)
            legacy_artifacts.append(rel)

        # Печать отчёта.
        ok = True
        if missing_in_staticfiles:
            ok = False
            self.stderr.write(
                self.style.ERROR(
                    "Нет копий в staticfiles/ (запустите collectstatic):"
                )
            )
            for relpath in sorted(missing_in_staticfiles):
                self.stderr.write(f"  - {relpath}")

        if size_mismatches:
            ok = False
            self.stderr.write(
                self.style.ERROR(
                    "Расхождение размеров static/src/ и staticfiles/:"
                )
            )
            for relpath, src_size, dst_size in sorted(size_mismatches):
                self.stderr.write(
                    f"  - {relpath}: src={src_size}, staticfiles={dst_size}"
                )

        if legacy_artifacts:
            self.stderr.write(
                self.style.WARNING(
                    "Legacy-артефакты в staticfiles/ без источника "
                    "(приберите отдельно):"
                )
            )
            for relpath in sorted(legacy_artifacts):
                self.stderr.write(f"  - {relpath}")

        if ok:
            self.stdout.write(self.style.SUCCESS("staticfiles/ синхронизирован с static/src/."))
            return

        if options["fail"]:
            raise CommandError(
                "staticfiles/ не синхронизирован с static/src/. "
                "Запустите `python manage.py collectstatic` или "
                "проверьте ручные правки в staticfiles/."
            )
        else:
            self.stderr.write(
                self.style.WARNING(
                    "Используйте --fail, чтобы превращать расхождения в CommandError (для CI)."
                )
            )

    def _resolve_static_root(self) -> Path:
        configured = getattr(settings, "STATIC_ROOT", "")
        if configured:
            return Path(configured)
        return Path(settings.BASE_DIR) / "staticfiles"


def _walk_synced(static_src: Path, static_root: Path):
    """Возвращает кортежи (relpath, src_path, dst_path) для файлов
    с расширениями ``.js``/``.css`` под ``static/src/``.
    """
    for src_path in static_src.rglob("*"):
        if not src_path.is_file():
            continue
        if src_path.suffix not in _SYNCED_EXTENSIONS:
            continue
        relpath = src_path.relative_to(static_src)
        dst_path = static_root / relpath
        yield relpath, src_path, dst_path


def _static_root() -> Path:
    configured = getattr(settings, "STATIC_ROOT", "")
    if configured:
        return Path(configured)
    return Path(settings.BASE_DIR) / "staticfiles"


def _static_src_root() -> Path:
    return Path(settings.BASE_DIR) / "static" / "src"


def _mirrored_roots(static_src: Path, static_root: Path):
    """Корень в ``static_root``, который зеркалит ``static_src``.

    По умолчанию ``collectstatic`` сохраняет структуру ``STATICFILES_DIRS``
    как есть — в нашем случае ``static/src/<rel>`` уходит в
    ``static_root/src/<rel>``. Если такой подкаталог существует, идём
    только по нему: так команда не ловит в качестве «legacy» статики
    ``django.contrib.admin``, ``django_htmx`` и другие пакеты,
    источник которых живёт вовне ``static/src/``.

    Альтернативная раскладка (``STATIC_ROOT`` хранит плоское зеркало)
    сознательно не поддерживается — она не соответствует тому, как
    ``collectstatic`` работает в нашем проекте.
    """
    primary = static_root / "src"
    if primary.exists():
        yield primary


def _matches_any(relpath: Path, patterns: tuple[str, ...]) -> bool:
    name = relpath.name
    if _MANIFEST_HASH_RE.match(name):
        return True
    if _GZIP_RE.search(name):
        return True
    return _matches_glob(name, patterns)


def _matches_glob(name: str, patterns: tuple[str, ...]) -> bool:
    """Минимальный glob-матчинг без ``fnmatch``.

    Достаточно для шаблонов ``*.bak``, ``test_marker.txt`` и других
    пользовательских ``--ignore``. ``fnmatch`` под Windows плохо
    переносит конструкции вида ``[0-9a-f]``, поэтому весь «сложный»
    матчинг вынесен в предикаты выше.
    """
    for pattern in patterns:
        if pattern == name:
            return True
        if pattern.startswith("*.") and name.endswith(pattern[1:]):
            return True
        if pattern.endswith("*") and name.startswith(pattern[:-1]):
            return True
        if "*" in pattern:
            head, _, _ = pattern.partition("*")
            tail, _, _ = pattern[::-1].partition("*")
            tail = tail[::-1]
            if name.startswith(head) and name.endswith(tail):
                return True
    return False
