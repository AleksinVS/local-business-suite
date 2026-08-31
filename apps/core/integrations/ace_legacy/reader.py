"""Запуск Windows-обёртки ACE без знания предметных таблиц.

Сам модуль не подключается к Access и не хранит строку подключения: это важно,
чтобы Linux/Django runtime не получил скрытую зависимость от COM/ACE.  Скрипт
PowerShell получает только явно разрешённые вызывающим профилем таблицы и пишет
нейтральный JSONL-снимок в уже проверенную рабочую директорию.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Iterable

from django.conf import settings


class AccessTransportError(RuntimeError):
    """Ошибка запуска либо безопасной read-only выгрузки ACE."""


def run_access_export(
    *,
    source: Path,
    output_dir: Path,
    tables: Iterable[str],
    sample_size: int = 5,
    inspect_only: bool = False,
    powershell_executable: str | None = None,
) -> dict:
    """Запустить ACE export и вернуть его transport manifest.

    ``output_dir`` должен быть проверен доменным вызывающим кодом. Transport не
    интерпретирует таблицы и не передаёт PowerShell произвольное SQL.
    """
    source = Path(source)
    output_dir = Path(output_dir)
    if os.name != "nt":
        raise AccessTransportError("ACE OLE DB доступен только на Windows-хосте.")
    if not source.is_file():
        raise AccessTransportError("Файл Access не найден.")
    if sample_size < 0 or sample_size > 20:
        raise AccessTransportError("Размер выборки должен быть от 0 до 20.")
    normalized_tables = [str(table).strip() for table in tables if str(table).strip()]
    if not normalized_tables:
        raise AccessTransportError("Для выгрузки не задана ни одна таблица.")

    script = Path(settings.BASE_DIR) / "scripts" / "windows" / "export_warehouse_access.ps1"
    if not script.is_file():
        raise AccessTransportError("Windows-скрипт ACE transport не найден.")
    output_dir.mkdir(parents=True, exist_ok=True)
    executable = powershell_executable or "powershell.exe"
    command = [
        executable,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-Source",
        str(source),
        "-OutputDir",
        str(output_dir),
        "-SampleSize",
        str(sample_size),
        "-Tables",
        *normalized_tables,
    ]
    if inspect_only:
        command.append("-InspectOnly")
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, encoding="utf-8")
    except OSError as exc:
        raise AccessTransportError("Не удалось запустить Windows PowerShell для ACE.") from exc
    if completed.returncode:
        # Script prints only a coded/sanitised error. Do not include source path
        # or command line in Django output/audit records.
        message = (completed.stderr or completed.stdout or "ACE export завершился с ошибкой.").strip()
        raise AccessTransportError(message[-2000:])
    manifest_path = output_dir / "transport-manifest.json"
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AccessTransportError("ACE export не создал корректный transport manifest.") from exc
