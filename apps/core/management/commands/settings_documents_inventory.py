import json
import os
import secrets
import stat
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.settings_center.document_hashes import document_hash
from apps.settings_center.document_registry import get_document_registry
from apps.settings_center.document_security import classify_secret_references
from apps.settings_center.registry import get_registry


class Command(BaseCommand):
    help = "Вывести безопасный инвентарь конфигурационных документов."

    def add_arguments(self, parser):
        parser.add_argument("--output", type=str)
        parser.add_argument("--format", choices=("json", "table"), default="json")

    def handle(self, *args, **options):
        registry = get_document_registry()
        try:
            registry.validate_defaults()
        except Exception as exc:
            raise CommandError(f"Git-дефолты документов не прошли проверку: {exc}") from exc

        descriptors = {
            descriptor.setting_id: descriptor for descriptor in get_registry().all()
        }
        rows = [
            self._inventory_row(spec, descriptors.get(spec.document_id))
            for spec in registry.all()
        ]
        rows.sort(key=lambda row: row["document_id"])
        result = (
            json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True)
            if options["format"] == "json"
            else self._table(rows)
        )
        if options.get("output"):
            self._safe_write_local_output(options["output"], result + "\n")
        else:
            self.stdout.write(result)

    def _inventory_row(self, spec, descriptor):
        default_path = (
            Path(settings.BASE_DIR) / spec.default_path if spec.default_path else None
        )
        expected_runtime = self._expected_runtime_path(spec)
        effective_runtime = self._effective_runtime_path(spec, expected_runtime)
        env_override = bool(
            effective_runtime
            and expected_runtime
            and self._normalized_path(effective_runtime)
            != self._normalized_path(expected_runtime)
        )
        default_payload, default_error = self._read_payload(default_path)
        runtime_payload, runtime_error = self._read_payload(effective_runtime)
        default_sha256 = document_hash(default_payload) if default_payload is not None else None
        runtime_sha256 = document_hash(runtime_payload) if runtime_payload is not None else None
        ambiguity = None
        if env_override:
            ambiguity = "env_override"
        elif runtime_error and runtime_error != "missing":
            ambiguity = "invalid_runtime"
        elif (
            runtime_sha256
            and default_sha256
            and runtime_sha256 != default_sha256
            and spec.storage_policy == "git_static"
        ):
            ambiguity = "static_runtime_drift"
        elif runtime_sha256 and default_sha256 and runtime_sha256 != default_sha256:
            ambiguity = "runtime_diff_requires_audit"

        return {
            "document_id": spec.document_id,
            "domain": spec.domain,
            "default_path": spec.default_path,
            "effective_runtime_path": str(effective_runtime) if effective_runtime else None,
            "expected_runtime_path": str(expected_runtime) if expected_runtime else None,
            "legacy_settings_path": spec.legacy_settings_path,
            "active_backend": spec.active_backend,
            "descriptor": descriptor.setting_id if descriptor else None,
            "validator": getattr(spec.validator, "__name__", None),
            "cross_document_ids": list(spec.cross_document_ids),
            "write_policy": spec.write_policy,
            "storage_policy": spec.storage_policy,
            "failure_policy": spec.failure_policy,
            "owner": spec.owner,
            "consumer_classes": list(spec.consumer_classes),
            "requires_restart": spec.requires_restart,
            "requires_reindex": spec.requires_reindex,
            "secret_scan": {
                "default": self._secret_scan(default_payload, default_error),
                "effective_runtime": self._secret_scan(runtime_payload, runtime_error),
            },
            "migration_ambiguity": ambiguity,
            "default_sha256": default_sha256,
            "runtime_sha256": runtime_sha256,
            "env_override": env_override,
            "defaults_valid": default_error is None,
            "runtime_state": runtime_error or "valid",
        }

    @staticmethod
    def _expected_runtime_path(spec):
        if spec.default_path is None:
            return None
        relative = Path(spec.default_path).relative_to("contracts")
        return Path(settings.RUNTIME_CONTRACTS_DIR) / relative

    @staticmethod
    def _effective_runtime_path(spec, expected_runtime):
        if spec.legacy_settings_path:
            configured = getattr(settings, spec.legacy_settings_path, None)
            if configured:
                return Path(configured)
        return expected_runtime

    @staticmethod
    def _normalized_path(path):
        return Path(os.path.abspath(os.fspath(path)))

    @staticmethod
    def _read_payload(path):
        if path is None:
            return None, "missing"
        if path.is_symlink():
            return None, "unsafe"
        if not path.exists():
            return None, "missing"
        if not path.is_file():
            return None, "unsafe"
        try:
            return json.loads(path.read_text(encoding="utf-8")), None
        except (OSError, UnicodeError, ValueError):
            return None, "invalid"

    @classmethod
    def _secret_scan(cls, payload, error):
        if error:
            return error
        return classify_secret_references(payload)

    @staticmethod
    def _safe_write_local_output(output, content):
        local_root = Path(settings.BASE_DIR) / ".local"
        local_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if local_root.is_symlink() or not local_root.is_dir():
            raise CommandError(".local должен быть обычным каталогом.")
        raw_path = Path(output)
        absolute = Path(
            os.path.abspath(raw_path if raw_path.is_absolute() else Path.cwd() / raw_path)
        )
        try:
            relative = absolute.relative_to(Path(os.path.abspath(local_root)))
        except ValueError as exc:
            raise CommandError("--output разрешён только внутри .local/") from exc
        if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
            raise CommandError("Некорректный путь --output.")
        if os.name == "nt":
            return Command._safe_write_windows(absolute, local_root, content)

        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        directory_fd = os.open(local_root, directory_flags)
        try:
            for part in relative.parts[:-1]:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=directory_fd)
                except FileExistsError:
                    pass
                next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = next_fd

            target_name = relative.name
            try:
                target_stat = os.stat(target_name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                target_stat = None
            if target_stat is not None and not stat.S_ISREG(target_stat.st_mode):
                raise CommandError("--output должен быть обычным файлом.")

            temporary_name = f".settings-inventory-{secrets.token_hex(12)}.tmp"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            file_fd = os.open(temporary_name, flags, 0o600, dir_fd=directory_fd)
            try:
                stream = os.fdopen(file_fd, "w", encoding="utf-8")
                file_fd = -1
                with stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(
                    temporary_name,
                    target_name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
                os.fsync(directory_fd)
            finally:
                if file_fd >= 0:
                    os.close(file_fd)
                try:
                    os.unlink(temporary_name, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass
        except OSError as exc:
            raise CommandError(f"Не удалось безопасно записать --output: {exc}") from exc
        finally:
            os.close(directory_fd)

    @staticmethod
    def _is_reparse_point(path):
        """Windows-safe reparse check; harmless and mockable on POSIX."""
        try:
            flags = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            return bool(os.stat(path, follow_symlinks=False).st_file_attributes & flags)
        except FileNotFoundError:
            return False
        except AttributeError:
            return Path(path).is_symlink()
        except OSError as exc:
            raise CommandError(f"Не удалось проверить reparse point: {exc}") from exc

    @staticmethod
    def _safe_write_windows(path, local_root, content):
        """Write through a reparse-point checked temp file and atomic MoveFileEx."""
        if Command._is_reparse_point(local_root):
            raise CommandError(".local не должен быть reparse point")
        current = local_root
        relative = path.relative_to(local_root)
        checked_directories = [local_root]
        for part in relative.parts[:-1]:
            current /= part
            if Command._is_reparse_point(current):
                raise CommandError("--output не должен проходить через reparse point")
            current.mkdir(mode=0o700, exist_ok=True)
            checked_directories.append(current)
        if Command._is_reparse_point(path):
            raise CommandError("--output не может быть reparse point")
        temporary = path.with_name(f".settings-inventory-{secrets.token_hex(12)}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        file_fd = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(file_fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if any(Command._is_reparse_point(item) for item in checked_directories):
                raise CommandError("reparse point появился перед заменой")
            if Command._is_reparse_point(path):
                raise CommandError("reparse point появился перед заменой")
            if os.name == "nt":
                import ctypes

                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                if not kernel32.MoveFileExW(str(temporary), str(path), 0x1 | 0x8):
                    raise OSError(ctypes.get_last_error(), "MoveFileExW failed")
            else:  # test/mocked POSIX branch
                os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _table(rows):
        headers = ("document_id", "storage_policy", "active_backend", "owner", "descriptor")
        lines = ["\t".join(headers)]
        lines.extend(
            "\t".join(str(row.get(header) or "-") for header in headers) for row in rows
        )
        return "\n".join(lines)
