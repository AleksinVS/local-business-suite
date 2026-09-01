"""Static architecture guards for migrated settings documents.

The settings registry is the authority for migrated document identifiers and
legacy compatibility paths.  This module keeps the corresponding source-tree
guard in production code so ``validate_architecture_contracts`` and Django
checks enforce the same boundary as the tests: application consumers must use
the repository, while file access remains confined to migration/compatibility
adapters.
"""

from __future__ import annotations

import ast
from pathlib import Path

from django.conf import settings

from .document_registry import get_document_registry


# These modules are the deliberately narrow compatibility boundary.  The
# bootstrap command may inspect/copy legacy files for transition support, and
# migration/inventory/repository services own the remaining file operations.
CENTRALIZED_DOCUMENT_FILE_ADAPTERS = frozenset(
    {
        Path("apps/core/contract_store.py"),
        Path("apps/core/contract_drift.py"),
        Path("apps/core/management/commands/bootstrap_runtime.py"),
        Path("apps/core/management/commands/settings_documents_inventory.py"),
        Path("apps/settings_center/architecture_validation.py"),
        Path("apps/settings_center/document_migration.py"),
        Path("apps/settings_center/document_repository.py"),
        Path("apps/settings_center/contract_services.py"),
        Path("apps/settings_center/access_migration_services.py"),
        # Registry declarations are the source of the default paths consumed
        # by the repository; they are not runtime consumers of those files.
        Path("apps/accounts/config_documents.py"),
        Path("apps/ai/config_documents.py"),
        Path("apps/analytics/config_documents.py"),
        Path("apps/core/config_documents.py"),
        Path("apps/memory/config_documents.py"),
        Path("apps/waiting_list/config_documents.py"),
        Path("apps/workorders/config_documents.py"),
        Path("apps/warehouse/config_documents.py"),
    }
)

MIGRATED_DOCUMENT_IO_NAMES = frozenset(
    {
        "load_json_file",
        "read_text",
        "write_text",
        "open",
        "atomic_write_json",
        "copy",
        "copyfile",
        "load",
        "dump",
        "read_bytes",
        "write_bytes",
        "replace",
        "atomic_write",
    }
)

# Payload attributes were a startup compatibility mechanism.  They are not a
# supported consumer API; in particular the waiting-list payload assignment
# was removed from config/settings.py in package 08.
DEPRECATED_PAYLOAD_SETTINGS = frozenset(
    {
        "LOCAL_BUSINESS_ROLE_RULES",
        "LOCAL_BUSINESS_WORKFLOW_RULES",
        "LOCAL_BUSINESS_WORKORDER_STATUS_COLORS",
        "LOCAL_BUSINESS_WAITING_LIST_STATUS_COLORS",
        "LOCAL_BUSINESS_INTEGRATION_REGISTRY",
        "LOCAL_BUSINESS_ANALYTICS_DATASETS",
        "LOCAL_BUSINESS_ANALYTICS_SOURCES",
        "LOCAL_BUSINESS_ANALYTICS_SCOPE_RULES",
        "LOCAL_BUSINESS_ANALYTICS_BUSINESS_FACTS",
        "LOCAL_BUSINESS_ANALYTICS_METRICS",
        "LOCAL_BUSINESS_ANALYTICS_MONITORS",
        "LOCAL_BUSINESS_ANALYTICS_DIAGNOSTIC_PLAYBOOKS",
        "LOCAL_BUSINESS_ANALYTICS_WORKFLOW_ROUTES",
        "LOCAL_BUSINESS_ANALYTICS_DEDUP_RULES",
        "LOCAL_BUSINESS_ANALYTICS_RETENTION_PROFILES",
        "LOCAL_BUSINESS_AI_REGISTRY",
        "LOCAL_BUSINESS_AI_TOOLS",
        "LOCAL_BUSINESS_AI_TASK_TYPES",
        "LOCAL_BUSINESS_AI_MODELS",
        "LOCAL_BUSINESS_AI_CHAT_SETTINGS",
        "LOCAL_BUSINESS_MEMORY_SOURCES",
        "LOCAL_BUSINESS_MEMORY_PROFILES",
        "LOCAL_BUSINESS_MEMORY_ROUTING",
        "LOCAL_BUSINESS_MEMORY_TRUST_POLICY",
        "LOCAL_BUSINESS_MEMORY_CLAIMS_POLICY",
        "LOCAL_BUSINESS_MEMORY_RETRIEVAL_BUDGET",
        "LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES",
        "LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES",
        "LOCAL_BUSINESS_MEMORY_GRAPH_SCHEMA",
    }
)


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _contains_migrated_filename(
    node: ast.AST,
    filenames: set[str],
    constants: dict[str, str] | None = None,
) -> bool:
    constants = constants or {}
    for child in ast.walk(node):
        value = None
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            value = child.value
        elif isinstance(child, ast.Name):
            value = constants.get(child.id)
        if value is not None:
            value = value.lower()
            if any(filename in value for filename in filenames):
                return True
    return False


def _contract_path_literal(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.replace("\\", "/")
    if normalized.startswith("contracts/") and normalized.endswith(".json"):
        return normalized
    return None


def _simple_contract_constants(
    tree: ast.AST,
    *,
    known_filenames: set[str] | None = None,
) -> dict[str, str]:
    known_filenames = known_filenames or set()
    constants: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                literal = _contract_path_literal(node.value.value)
                if literal is None and isinstance(node.value.value, str):
                    filename = node.value.value.replace("\\", "/").lower()
                    if filename in known_filenames:
                        literal = filename
                if literal is not None:
                    constants[target.id] = literal
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if isinstance(node.value, ast.Constant):
                literal = _contract_path_literal(node.value.value)
                if literal is None and isinstance(node.value.value, str):
                    filename = node.value.value.replace("\\", "/").lower()
                    if filename in known_filenames:
                        literal = filename
                if literal is not None:
                    constants[node.target.id] = literal
    return constants


def find_unregistered_contracts(*, root: Path | None = None) -> tuple[str, ...]:
    """Return JSON files below ``contracts/`` absent from the document registry."""

    project_root = Path(root or settings.BASE_DIR).resolve()
    contracts_root = project_root / "contracts"
    actual = {
        path.relative_to(project_root).as_posix()
        for path in contracts_root.rglob("*.json")
        if path.is_file()
        and ".desc.json" not in path.name
        and "schemas" not in path.relative_to(contracts_root).parts
    }
    registered = {
        str(spec.default_path).replace("\\", "/")
        for spec in get_document_registry().all()
        if spec.default_path is not None
    }
    return tuple(sorted(actual ^ registered))


def validate_contract_registry_coverage(*, root: Path | None = None) -> None:
    """Raise when tracked value contracts and registry entries are not equal."""

    differences = find_unregistered_contracts(root=root)
    if differences:
        raise RuntimeError(
            "Реестр документов не совпадает с contracts/: "
            + ", ".join(differences)
        )


def find_migrated_document_access_violations(*, root: Path | None = None) -> tuple[str, ...]:
    """Return direct migrated-document access outside approved adapters.

    This is intentionally a source-tree check, not a runtime monkeypatch.  A
    violation is reported for either a direct legacy ``settings`` attribute or
    an I/O call containing a migrated default filename, including a simple
    string constant passed to the call.  Fully dynamic paths cannot be proven
    from AST alone; their ownership remains an explicit adapter/code-review
    responsibility.  Tests and Django migrations are excluded because they
    are not production consumers.
    """

    project_root = Path(root or settings.BASE_DIR).resolve()
    registry = get_document_registry()
    migrated_specs = tuple(registry.all())
    forbidden_settings = {
        spec.legacy_settings_path
        for spec in migrated_specs
        if spec.legacy_settings_path
    }
    forbidden_settings.update(DEPRECATED_PAYLOAD_SETTINGS)
    migrated_filenames = {
        Path(spec.default_path).name.lower()
        for spec in migrated_specs
        if spec.default_path
    }
    migrated_basenames = set(migrated_filenames)
    registered_paths = {
        str(spec.default_path).replace("\\", "/")
        for spec in migrated_specs
        if spec.default_path is not None
    }
    violations: list[str] = []

    source_roots = tuple(
        root_path
        for root_path in (
            project_root / "apps",
            project_root / "services" / "agent_runtime",
        )
        if root_path.is_dir()
    )
    for source_root in source_roots:
        for path in source_root.rglob("*.py"):
            relative = path.relative_to(project_root)
            if (
                relative in CENTRALIZED_DOCUMENT_FILE_ADAPTERS
                or "migrations" in relative.parts
                or path.name.startswith("test")
                or "tests" in relative.parts
            ):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
            except (OSError, SyntaxError) as exc:
                violations.append(f"{relative}:source-unreadable:{exc}")
                continue
            simple_constants = _simple_contract_constants(
                tree,
                known_filenames=migrated_basenames,
            )
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant):
                    literal = _contract_path_literal(node.value)
                    if literal is not None:
                        if literal not in registered_paths:
                            violations.append(f"{relative}:{node.lineno}:unregistered:{literal}")
                        else:
                            violations.append(f"{relative}:{node.lineno}:direct:{literal}")
                if isinstance(node, ast.Attribute):
                    if (
                        isinstance(node.value, ast.Name)
                        and node.value.id == "settings"
                        and node.attr in forbidden_settings
                    ):
                        violations.append(f"{relative}:{node.lineno}:settings.{node.attr}")
                elif isinstance(node, ast.Call):
                    if (
                        _call_name(node) == "getattr"
                        and len(node.args) >= 2
                        and isinstance(node.args[0], ast.Name)
                        and node.args[0].id == "settings"
                        and isinstance(node.args[1], ast.Constant)
                        and node.args[1].value in forbidden_settings
                    ):
                        violations.append(
                            f"{relative}:{node.lineno}:getattr(settings,{node.args[1].value})"
                        )
                    if (
                        _call_name(node) in MIGRATED_DOCUMENT_IO_NAMES
                        and _contains_migrated_filename(
                            node,
                            migrated_filenames | migrated_basenames,
                            simple_constants,
                        )
                    ):
                        violations.append(f"{relative}:{node.lineno}:{_call_name(node)}")
    return tuple(sorted(set(violations)))


def validate_migrated_document_file_access(*, root: Path | None = None) -> None:
    """Raise when a production consumer bypasses the settings repository."""

    violations = find_migrated_document_access_violations(root=root)
    if violations:
        rendered = "; ".join(violations)
        raise RuntimeError(
            "Мигрированные документы настроек читаются или записываются вне "
            f"централизованных адаптеров: {rendered}"
        )
