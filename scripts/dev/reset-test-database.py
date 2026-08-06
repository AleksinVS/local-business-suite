#!/usr/bin/env python3
"""Удаляет только локальные SQLite-файлы повторно используемой тестовой БД."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_ROOT = (PROJECT_ROOT / ".local").resolve()
PATTERN = "test-default*.sqlite3*"


def main() -> None:
    removed: list[Path] = []
    for path in sorted(LOCAL_ROOT.glob(PATTERN)):
        resolved = path.resolve()
        if resolved.parent != LOCAL_ROOT or not resolved.is_file():
            raise RuntimeError(f"Отказ от удаления неожиданного пути: {resolved}")
        resolved.unlink()
        removed.append(resolved)

    if not removed:
        print("Сохраненная тестовая SQLite-база отсутствует.")
        return

    for path in removed:
        print(f"Удален тестовый файл: {path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
