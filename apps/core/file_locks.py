"""Межпроцессные блокировки файлов для Linux и Windows.

Блокировка хранится в отдельном постоянном lock-файле. Удалять его после
освобождения нельзя: другой процесс уже может держать открытый дескриптор этого
же файла. При отсутствии платформенного механизма работа завершается закрытым
отказом, а не продолжается без синхронизации.
"""
from __future__ import annotations

import contextlib
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings


class FileLockTimeoutError(TimeoutError):
    """Блокировка не была получена за отведённое время."""


def access_control_write_lock_path() -> Path:
    """Общий lock для контракта ролей и изменений членства в ролях."""
    root = Path(getattr(settings, "RUNTIME_CONTRACTS_DIR", Path(settings.DATA_DIR) / "contracts"))
    return root / ".settings-contract-write.lock"


def memory_source_lifecycle_lock_path() -> Path:
    """Общий lock для статуса источника и длительных операций памяти/FileHub."""
    root = Path(getattr(settings, "RUNTIME_CONTRACTS_DIR", Path(settings.DATA_DIR) / "contracts"))
    return root / ".memory-source-lifecycle.lock"


@contextlib.contextmanager
def exclusive_file_lock(path, *, timeout: float = 10.0, poll_interval: float = 0.05):
    """Получить исключительную межпроцессную блокировку с ограничением времени."""
    lock_path = Path(os.path.abspath(os.fspath(path)))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _open_lock_file(lock_path) as lock_file:
        if lock_file.seek(0, 2) == 0:
            lock_file.write(b"0")
            lock_file.flush()
        lock_file.seek(0)
        _acquire(lock_file, timeout=timeout, poll_interval=poll_interval)
        held = HeldFileLock(lock_path, lock_file)
        try:
            held.assert_current()
            yield held
        finally:
            try:
                held.assert_current()
            finally:
                _release(lock_file)


@dataclass(frozen=True)
class HeldFileLock:
    """Закреплённый inode lock-файла с проверкой подмены имени."""

    path: Path
    stream: object

    def assert_current(self) -> None:
        opened = os.fstat(self.stream.fileno())
        try:
            current = os.stat(self.path, follow_symlinks=False)
        except OSError as exc:
            raise RuntimeError("Lock-файл исчез или был заменён.") from exc
        if (
            stat.S_ISLNK(current.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or opened.st_nlink < 1
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise RuntimeError("Lock-файл исчез или был заменён.")


def _open_lock_file(path: Path):
    """Открыть lock без следования symlink/reparse там, где это поддерживается."""

    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if os.name == "nt":
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            info = None
        if info is not None and (
            stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            raise RuntimeError("Lock-файл является ссылкой/reparse point.")
        descriptor = os.open(path, flags | nofollow, 0o600)
        try:
            opened = os.fstat(descriptor)
            current = os.lstat(path)
            if (
                stat.S_ISLNK(current.st_mode)
                or getattr(current, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
            ):
                raise RuntimeError("Lock-файл был заменён при открытии.")
        except Exception:
            os.close(descriptor)
            raise
        return os.fdopen(descriptor, "r+b")

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    directory_fd = os.open(os.sep, directory_flags | nofollow)
    try:
        for component in path.parent.parts[1:]:
            child_fd = os.open(
                component,
                directory_flags | nofollow,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = child_fd
        descriptor = os.open(
            path.name,
            flags | nofollow,
            0o600,
            dir_fd=directory_fd,
        )
    finally:
        os.close(directory_fd)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise RuntimeError("Lock-файл не является regular file.")
    return os.fdopen(descriptor, "r+b")


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
