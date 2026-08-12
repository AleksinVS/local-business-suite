"""Межпроцессные блокировки файлов для Linux и Windows.

Блокировка хранится в отдельном постоянном lock-файле. Удалять его после
освобождения нельзя: другой процесс уже может держать открытый дескриптор этого
же файла. При отсутствии платформенного механизма работа завершается закрытым
отказом, а не продолжается без синхронизации.
"""
from __future__ import annotations

import contextlib
import time
from pathlib import Path

from django.conf import settings


class FileLockTimeoutError(TimeoutError):
    """Блокировка не была получена за отведённое время."""


def access_control_write_lock_path() -> Path:
    """Общий lock для контракта ролей и изменений членства в ролях."""
    root = Path(getattr(settings, "RUNTIME_CONTRACTS_DIR", Path(settings.DATA_DIR) / "contracts"))
    return root / ".settings-contract-write.lock"


@contextlib.contextmanager
def exclusive_file_lock(path, *, timeout: float = 10.0, poll_interval: float = 0.05):
    """Получить исключительную межпроцессную блокировку с ограничением времени."""
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        if lock_file.seek(0, 2) == 0:
            lock_file.write(b"0")
            lock_file.flush()
        lock_file.seek(0)
        _acquire(lock_file, timeout=timeout, poll_interval=poll_interval)
        try:
            yield
        finally:
            _release(lock_file)


def _acquire(lock_file, *, timeout: float, poll_interval: float) -> None:
    deadline = time.monotonic() + timeout
    fcntl = _import_fcntl()
    if fcntl is not None:
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise FileLockTimeoutError("Истекло время ожидания блокировки файла.") from exc
                time.sleep(poll_interval)

    msvcrt = _import_msvcrt()
    if msvcrt is not None:
        while True:
            try:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise FileLockTimeoutError("Истекло время ожидания блокировки файла.") from exc
                time.sleep(poll_interval)

    raise RuntimeError("Платформа не предоставляет поддерживаемую межпроцессную блокировку файлов.")


def _release(lock_file) -> None:
    fcntl = _import_fcntl()
    if fcntl is not None:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        return
    msvcrt = _import_msvcrt()
    if msvcrt is not None:
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def _import_fcntl():
    try:
        import fcntl

        return fcntl
    except ImportError:
        return None


def _import_msvcrt():
    try:
        import msvcrt

        return msvcrt
    except ImportError:
        return None
