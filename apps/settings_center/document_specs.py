"""Неизменяемые метаданные документов, принадлежащие доменным приложениям."""

import inspect
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable

STORAGE_POLICIES = frozenset({"database_override", "git_static", "generated_file"})
FAILURE_POLICIES = frozenset({"fail_closed", "visible_default_fallback"})
WRITE_POLICIES = frozenset({"read_only", "editable", "requires_domain_workflow"})
PERMISSIONS = frozenset({"manage_settings", "manage_users"})
DELIVERY_SCOPES = frozenset({"django", "agent_runtime", "django+agent_runtime", "job"})
ACTIVE_BACKENDS = frozenset({"legacy_file", "git", "database", "generated_file"})
SENSITIVITIES = frozenset({"public", "internal", "restricted"})


@dataclass(frozen=True)
class ConfigDocumentSpec:
    document_id: str
    domain: str
    storage_policy: str
    default_path: str | None
    schema_version: int
    validator: Callable | None
    failure_policy: str
    write_policy: str
    required_permission: str
    owner: str
    legacy_settings_path: str | None = None
    cross_document_ids: tuple[str, ...] = ()
    cross_validator: Callable | None = None
    requires_restart: bool = False
    requires_reindex: bool = False
    delivery_scope: str = "django"
    consumer_classes: tuple[str, ...] = ()
    sensitivity: str = "internal"
    active_backend: str = "legacy_file"

    def __post_init__(self):
        if not all(isinstance(value, str) and value.strip() for value in (self.document_id, self.domain, self.owner)):
            raise ValueError("document_id, domain and owner are required")
        if self.storage_policy not in STORAGE_POLICIES:
            raise ValueError(f"Invalid storage policy: {self.document_id}")
        if self.failure_policy not in FAILURE_POLICIES:
            raise ValueError(f"Invalid failure policy: {self.document_id}")
        if type(self.schema_version) is not int or self.schema_version <= 0:
            raise ValueError(f"schema_version must be positive: {self.document_id}")
        if self.write_policy not in WRITE_POLICIES:
            raise ValueError(f"Invalid write policy: {self.document_id}")
        if self.required_permission not in PERMISSIONS:
            raise ValueError(f"Invalid write metadata: {self.document_id}")
        if self.delivery_scope not in DELIVERY_SCOPES:
            raise ValueError(f"Invalid delivery scope: {self.document_id}")
        if self.active_backend not in ACTIVE_BACKENDS:
            raise ValueError(f"Invalid active backend: {self.document_id}")
        if self.sensitivity not in SENSITIVITIES:
            raise ValueError(f"Invalid sensitivity: {self.document_id}")
        if self.storage_policy == "git_static" and self.active_backend != "git":
            raise ValueError(f"git_static must use git backend: {self.document_id}")
        if (
            self.storage_policy == "database_override"
            and self.active_backend not in {"legacy_file", "database"}
        ):
            raise ValueError(
                f"database_override must use legacy_file or database backend: {self.document_id}"
            )
        if self.storage_policy == "generated_file" and self.active_backend != "generated_file":
            raise ValueError(f"generated_file must use generated_file backend: {self.document_id}")
        if self.default_path is None and self.storage_policy != "generated_file":
            raise ValueError(f"Only generated_file may omit default_path: {self.document_id}")
        if self.default_path is not None:
            path = PurePosixPath(self.default_path)
            if (
                path.is_absolute()
                or ".." in path.parts
                or not path.parts
                or path.parts[0] != "contracts"
                or path.suffix != ".json"
            ):
                raise ValueError(f"default_path must be below contracts/: {self.document_id}")
        if self.storage_policy == "database_override" and self.write_policy == "read_only":
            raise ValueError(f"database_override cannot be read_only: {self.document_id}")
        if self.storage_policy in {"git_static", "generated_file"} and self.write_policy != "read_only":
            raise ValueError(f"static/generated document must be read_only: {self.document_id}")
        if self.storage_policy == "database_override" and not callable(self.validator):
            raise ValueError(f"database_override requires callable validator: {self.document_id}")
        if self.validator is not None and not callable(self.validator):
            raise ValueError(f"validator must be callable: {self.document_id}")
        if not isinstance(self.cross_document_ids, tuple) or any(
            not isinstance(item, str) or not item for item in self.cross_document_ids
        ):
            raise ValueError(f"cross_document_ids must be a tuple of ids: {self.document_id}")
        if len(self.cross_document_ids) != len(set(self.cross_document_ids)):
            raise ValueError(f"Duplicate document dependency: {self.document_id}")
        if bool(self.cross_document_ids) != bool(self.cross_validator):
            raise ValueError(
                f"Dependencies and cross_validator must be declared together: {self.document_id}"
            )
        if self.cross_validator is not None and (
            not callable(self.cross_validator)
            or len(inspect.signature(self.cross_validator).parameters) != 2
        ):
            raise ValueError(
                f"cross_validator must accept (candidate, related_payloads): {self.document_id}"
            )
        if self.failure_policy == "visible_default_fallback" and self.sensitivity == "restricted":
            raise ValueError(f"security/privacy document cannot fallback: {self.document_id}")
        if not isinstance(self.consumer_classes, tuple) or any(
            not isinstance(item, str) or not item for item in self.consumer_classes
        ):
            raise ValueError(f"consumer_classes must be a tuple: {self.document_id}")
        if self.legacy_settings_path is not None and (
            not isinstance(self.legacy_settings_path, str)
            or not self.legacy_settings_path.startswith("LOCAL_BUSINESS_")
        ):
            raise ValueError(f"Invalid legacy settings path: {self.document_id}")
