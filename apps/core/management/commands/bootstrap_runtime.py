"""``manage.py bootstrap_runtime`` — идемпотентная первичная подготовка runtime.

Команда берёт на себя побочные эффекты, которые раньше выполнялись НА ИМПОРТЕ
``config/settings.py`` (создание ~20 каталогов в ``data/`` и копирование дефолтных
контрактов ``contracts/`` -> ``data/contracts/``). Импорт настроек теперь чистый
(без записи на диск), а подготовку окружения выполняет эта явная команда:
в проде — из ``docker/entrypoint.prod.sh`` перед ``migrate``, локально — при первом
запуске (см. README и docs/deployment/DEPLOYMENT.md).

Методическая заметка (обучающий контур): запись на диск при импорте конфигурации —
это скрытый побочный эффект. Он ломает read-only-развёртывания (immutable
infrastructure), создаёт гонки при параллельном старте нескольких процессов и
заставляет КАЖДУЮ ``manage.py``-команду (даже ``check`` или ``help``) платить за
mkdir/копирование. Явная идемпотентная bootstrap-команда переносит эту работу в
единственную управляемую точку: её запускают один раз при развёртывании, повторный
запуск безопасен, а импорт настроек снова становится дешёвым и без сюрпризов.

Идемпотентность: каталоги создаются с ``exist_ok=True``; рабочая копия контракта
копируется из дефолта ТОЛЬКО если её ещё нет — существующие рабочие копии (могли
быть отредактированы через Settings Center) не затираются.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


# Имена файлов, которые лежат в ``contracts/`` рядом с настоящими контрактами, но
# НЕ являются рабочими контрактами и не должны попадать в ``data/contracts/``
# (так же вело себя прежнее копирование на импорте — оно трогало только сами
# контракты, а не описания структуры и JSON-схемы).
_SKIP_CONTRACT_NAMES = {".desc.json"}
_SKIP_CONTRACT_TOP_DIRS = {"schemas"}


def _runtime_directories():
    """Каталоги ``data/``, которые раньше создавались на импорте settings.

    Строятся от ``settings.DATA_DIR`` (её можно вынести через
    ``LOCAL_BUSINESS_DATA_DIR``), поэтому команда корректна и при перенесённом
    каталоге данных, и во временной среде теста.
    """
    data_dir = Path(settings.DATA_DIR)
    runtime_contracts_dir = Path(settings.RUNTIME_CONTRACTS_DIR)
    return [
        data_dir / "db",
        data_dir / "media",
        data_dir / "logs",
        data_dir / "contracts",
        data_dir / "knowledge_repo",
        data_dir / "queues",
        data_dir / "indexes" / "fulltext",
        data_dir / "indexes" / "vector",
        data_dir / "indexes" / "graph",
        data_dir / "processing" / "raw_quarantine",
        data_dir / "processing" / "safe_work",
        data_dir / "processing" / "extraction_packets",
        data_dir / "processing" / "cleanup_manifests",
        data_dir / "cache",
        data_dir / "analytics" / "duckdb",
        runtime_contracts_dir / "ai",
        runtime_contracts_dir / "integrations",
        runtime_contracts_dir / "analytics",
    ]


def _iter_default_contracts(default_dir: Path):
    """Пары (default_file, relative_path) для контрактов, подлежащих копированию.

    Пропускает ``schemas/`` и ``.desc.json`` — это описания, а не рабочие данные;
    так рабочая копия ``data/contracts/`` повторяет ровно тот состав, что давало
    прежнее копирование на импорте.
    """
    for default_file in sorted(default_dir.rglob("*.json")):
        if not default_file.is_file():
            continue
        relative = default_file.relative_to(default_dir)
        if relative.parts and relative.parts[0] in _SKIP_CONTRACT_TOP_DIRS:
            continue
        if default_file.name in _SKIP_CONTRACT_NAMES:
            continue
        yield default_file, relative


class Command(BaseCommand):
    help = (
        "Идемпотентно готовит runtime-окружение: создаёт каталоги data/ и копирует "
        "дефолтные контракты в data/contracts/, если рабочей копии ещё нет. "
        "Заменяет побочные эффекты, ранее выполнявшиеся на импорте config/settings.py."
    )

    # Bootstrap выполняется ДО того, как готовы каталоги и рабочие копии
    # контрактов, поэтому не должен блокироваться system-check'ами (в частности,
    # проверкой контрактов apps.core.checks, которая читает как раз data/contracts/).
    requires_system_checks: tuple = ()

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать, что было бы создано/скопировано, ничего не записывая.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        default_dir = Path(settings.DEFAULT_CONTRACTS_DIR)
        runtime_contracts_dir = Path(settings.RUNTIME_CONTRACTS_DIR)

        created_dirs = 0
        for directory in _runtime_directories():
            if directory.exists():
                continue
            created_dirs += 1
            if dry_run:
                self.stdout.write(f"[dry-run] mkdir {directory}")
            else:
                directory.mkdir(parents=True, exist_ok=True)

        copied = 0
        skipped_existing = 0
        for default_file, relative in _iter_default_contracts(default_dir):
            runtime_file = runtime_contracts_dir / relative
            if runtime_file.exists():
                skipped_existing += 1
                continue
            copied += 1
            if dry_run:
                self.stdout.write(f"[dry-run] copy {default_file} -> {runtime_file}")
            else:
                runtime_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(default_file, runtime_file)

        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}bootstrap_runtime: каталогов создано {created_dirs}, "
                f"контрактов скопировано {copied}, "
                f"рабочих копий уже было {skipped_existing}."
            )
        )
