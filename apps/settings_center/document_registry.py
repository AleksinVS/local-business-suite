from __future__ import annotations

from functools import lru_cache
from importlib import import_module
import json
from dataclasses import replace
from pathlib import Path

from django.conf import settings

from .document_specs import ConfigDocumentSpec

SPEC_MODULES = (
    "apps.core.config_documents",
    "apps.accounts.config_documents",
    "apps.workorders.config_documents",
    "apps.waiting_list.config_documents",
    "apps.ai.config_documents",
    "apps.memory.config_documents",
    "apps.analytics.config_documents",
    "apps.warehouse.config_documents",
)

# Документы попадают сюда только после отдельной приемки consumer/writer среза.
# Deployment allowlist не может включить ещё не выпущенный backend.
DATABASE_BACKEND_RELEASED_DOCUMENT_IDS = frozenset(
    {
        "core.contract.role_rules",
        "core.contract.workflow_rules",
        "waiting_list.contract.status_colors",
        "workorders.contract.status_colors",
        "ai.contract.chat_settings",
        # Memory/FileHub consumers and their domain writers are released as a
        # complete database-override slice.  The private deployment allowlist
        # remains empty until a deployment explicitly opts into this slice.
        "memory.contract.sources",
        "memory.contract.profiles",
        "memory.contract.routing",
        "memory.contract.trust_policy",
        "memory.contract.retrieval_budget",
        "memory.contract.ingestion_profiles",
        "memory.contract.file_organization_profiles",
        "memory.contract.graph_schema",
        "warehouse.settings",
    }
)

class ConfigDocumentRegistry:
    def __init__(self, specs, *, validate_default_paths=True):
        specs = tuple(specs)
        if any(not isinstance(spec, ConfigDocumentSpec) for spec in specs):
            raise TypeError("Config document registry accepts only ConfigDocumentSpec values")
        ids = [s.document_id for s in specs]
        paths = [s.default_path for s in specs if s.default_path is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate document_id")
        if len(paths) != len(set(paths)):
            raise ValueError("Duplicate default_path")
        known = set(ids)
        graph = {s.document_id: set(s.cross_document_ids) for s in specs}
        for node, deps in graph.items():
            if node in deps:
                raise ValueError(f"Self document dependency for {node}")
            unknown = deps - known
            if unknown:
                raise ValueError(f"Invalid document dependency for {node}")

        visiting, visited = set(), set()

        def visit(node):
            if node in visiting:
                raise ValueError("Document dependency cycle")
            if node in visited:
                return
            visiting.add(node)
            for dependency in graph[node]:
                visit(dependency)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)
        self._by_id = {s.document_id: s for s in specs}
        self._graph = graph
        if validate_default_paths:
            self._validate_default_paths()

    def all(self):
        return tuple(self._by_id.values())

    def get(self, document_id):
        try:
            return self._by_id[document_id]
        except KeyError as exc:
            raise LookupError(f"Unknown document_id '{document_id}'.") from exc

    def by_storage_policy(self, policy):
        return tuple(s for s in self.all() if s.storage_policy == policy)

    def dependency_closure(self, document_ids):
        selected = set(document_ids)
        pending = list(selected)
        while pending:
            node = pending.pop()
            self.get(node)
            for dependency in self._graph[node]:
                if dependency not in selected:
                    selected.add(dependency)
                    pending.append(dependency)
        return tuple(sorted(selected))

    def connected_validation_scope(self, document_ids):
        graph = {node: set(dependencies) for node, dependencies in self._graph.items()}
        for node, dependencies in self._graph.items():
            for dependency in dependencies:
                graph[dependency].add(node)
        selected = set(document_ids)
        pending = list(selected)
        while pending:
            node = pending.pop()
            self.get(node)
            for related in graph[node]:
                if related not in selected:
                    selected.add(related)
                    pending.append(related)
        return tuple(sorted(selected))

    def validate_defaults(self):
        payloads = {}
        for spec in self.all():
            if spec.default_path is None:
                continue
            path = Path(settings.BASE_DIR) / spec.default_path
            payload = json.loads(path.read_text(encoding="utf-8"))
            if spec.validator is not None:
                spec.validator(payload)
            payloads[spec.document_id] = payload
        for spec in self.all():
            if spec.cross_validator is None:
                continue
            related = {item: payloads[item] for item in spec.cross_document_ids}
            spec.cross_validator(payloads[spec.document_id], related)
        return True

    def _validate_default_paths(self):
        contracts_root = (Path(settings.BASE_DIR) / "contracts").resolve()
        for spec in self.all():
            if spec.default_path is None:
                continue
            path = Path(settings.BASE_DIR) / spec.default_path
            resolved = path.resolve()
            if contracts_root not in resolved.parents or path.is_symlink() or not path.is_file():
                raise ValueError(f"Unsafe or missing default_path: {spec.document_id}")


@lru_cache(maxsize=1)
def get_document_registry():
    specs = []
    for module_name in SPEC_MODULES:
        module = import_module(module_name)
        specs.extend(module.get_document_specs())
    base_registry = ConfigDocumentRegistry(specs)
    database_override_ids = frozenset(
        spec.document_id
        for spec in base_registry.all()
        if spec.storage_policy == "database_override"
    )
    if DATABASE_BACKEND_RELEASED_DOCUMENT_IDS != database_override_ids:
        raise ValueError(
            "Database backend release set must cover exactly every database_override document: "
            + ", ".join(sorted(database_override_ids ^ DATABASE_BACKEND_RELEASED_DOCUMENT_IDS))
        )
    allowlist = tuple(
        getattr(settings, "LOCAL_BUSINESS_SETTINGS_DOCUMENT_DB_ALLOWLIST", ())
    )
    if len(allowlist) != len(set(allowlist)):
        raise ValueError("Database document allowlist contains duplicate IDs")
    unknown = sorted(set(allowlist) - {spec.document_id for spec in base_registry.all()})
    if unknown:
        raise ValueError("Unknown database document allowlist IDs: " + ", ".join(unknown))
    unreleased = sorted(set(allowlist) - DATABASE_BACKEND_RELEASED_DOCUMENT_IDS)
    if unreleased:
        raise ValueError("Database backend is not released for: " + ", ".join(unreleased))
    invalid_policy = sorted(
        document_id
        for document_id in allowlist
        if base_registry.get(document_id).storage_policy != "database_override"
    )
    if invalid_policy:
        raise ValueError("Database allowlist contains non-runtime documents: " + ", ".join(invalid_policy))
    for document_id in allowlist:
        connected = set(base_registry.connected_validation_scope((document_id,)))
        if not connected.issubset(allowlist):
            raise ValueError(
                "Database allowlist must contain the full connected slice: "
                + ", ".join(sorted(connected))
            )
    selected = set(allowlist)
    return ConfigDocumentRegistry(
        tuple(
            replace(spec, active_backend="database")
            if spec.document_id in selected
            else spec
            for spec in base_registry.all()
        )
    )
