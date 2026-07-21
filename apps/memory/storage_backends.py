from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from .document_ingestion import sha256_file


@dataclass(frozen=True)
class StorageWriteResult:
    storage_backend: str
    storage_ref: str
    relative_path: str
    sha256: str
    size_bytes: int


class ManagedFSStorageBackend:
    storage_backend = "managed_fs"

    def __init__(self, root: Path):
        self.root = Path(root)

    def copy_from_path(self, source_path: Path, *, target_relative_path: str, expected_hash: str, expected_size: int) -> StorageWriteResult:
        source_path = Path(source_path)
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(f"Source file is unavailable: {source_path}")
        target_path = self.resolve_relative_path(target_relative_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = target_path.with_name(f".{target_path.name}.{uuid.uuid4().hex}.tmp")
        shutil.copy2(source_path, temporary_path)
        actual_hash = sha256_file(temporary_path)
        actual_size = temporary_path.stat().st_size
        if actual_hash != expected_hash or actual_size != expected_size:
            temporary_path.unlink(missing_ok=True)
            raise ValueError("Managed copy verification failed.")
        temporary_path.replace(target_path)
        return StorageWriteResult(
            storage_backend=self.storage_backend,
            storage_ref=str(target_path),
            relative_path=self.relative_to_root(target_path),
            sha256=actual_hash,
            size_bytes=actual_size,
        )

    def verify(self, storage_ref: str, *, expected_hash: str, expected_size: int) -> bool:
        path = Path(storage_ref)
        if not path.exists() or not path.is_file():
            return False
        return path.stat().st_size == expected_size and sha256_file(path) == expected_hash

    def quarantine_source(self, source_path: Path, *, quarantine_relative_path: str) -> StorageWriteResult:
        source_path = Path(source_path)
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(f"Source file is unavailable for quarantine: {source_path}")
        target_path = self.resolve_relative_path(quarantine_relative_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_path), str(target_path))
        return StorageWriteResult(
            storage_backend=self.storage_backend,
            storage_ref=str(target_path),
            relative_path=self.relative_to_root(target_path),
            sha256=sha256_file(target_path),
            size_bytes=target_path.stat().st_size,
        )

    def purge(self, storage_ref: str) -> bool:
        path = Path(storage_ref)
        if not path.exists():
            return False
        if not path.is_file():
            raise ValueError("Only files can be purged by managed_fs backend.")
        path.unlink()
        return True

    def resolve_relative_path(self, relative_path: str) -> Path:
        relative = Path(str(relative_path or "").replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Managed storage path must be relative and stay inside managed root.")
        target = (self.root / relative).resolve()
        root = self.root.resolve()
        if target != root and root not in target.parents:
            raise ValueError("Managed storage path escapes managed root.")
        return target

    def relative_to_root(self, path: Path) -> str:
        return Path(path).resolve().relative_to(self.root.resolve()).as_posix()
