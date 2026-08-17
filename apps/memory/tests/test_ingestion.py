"""Тесты ожиданий bootstrap и пайплайна ingestion документов."""
from apps.memory.tests._common import *  # noqa: F401,F403
from apps.memory.tests._common import _memory_ingestion_profiles_with_acl  # noqa: F401
from apps.memory.services import can_access_source_object


class MemoryIngestionBootstrapExpectationTests(MemoryModelFactoryMixin, TestCase):
    databases = RUNTIME_DATABASES
    def test_bootstrap_models_expose_expected_fields_when_available(self):
        available_models = []

        for model_name, expected_fields in MEMORY_INGESTION_BOOTSTRAP_MODELS.items():
            model = get_optional_memory_model(model_name)
            if model is None:
                continue
            available_models.append(model_name)
            with self.subTest(model=model_name):
                field_names = {field.name for field in model._meta.get_fields()}
                self.assertTrue(
                    expected_fields.issubset(field_names),
                    f"{model_name} is missing fields: {sorted(expected_fields - field_names)}",
                )

        if not available_models:
            self.skipTest("memory ingestion/bootstrap models are not implemented yet")

    def test_bootstrap_models_are_registered_in_admin_when_available(self):
        available_models = []

        for model_name in MEMORY_INGESTION_BOOTSTRAP_MODELS:
            model = get_optional_memory_model(model_name)
            if model is None:
                continue
            available_models.append(model_name)
            with self.subTest(model=model_name):
                self.assertIn(model, django_admin.site._registry)
                self.assertEqual(
                    django_admin.site._registry[model].__class__.__name__,
                    f"{model_name}Admin",
                )

        if not available_models:
            self.skipTest("memory ingestion/bootstrap admin registrations are not implemented yet")

    def test_discovery_and_ingestion_commands_accept_dry_run_when_available(self):
        command_cases = (
            ("memory_discover_source", ["--source-code", "bootstrap_test_source", "--dry-run"]),
            ("memory_ingest_source", ["--source-code", "bootstrap_test_source", "--dry-run"]),
        )
        available_commands = get_commands()
        checked_commands = []

        self.create_source(code="bootstrap_test_source", source_kind="documentation", index_profiles=["fulltext_default"])

        for command_name, args in command_cases:
            if command_name not in available_commands:
                continue
            checked_commands.append(command_name)
            with self.subTest(command=command_name):
                try:
                    call_command(command_name, *args, verbosity=0)
                except CommandError as exc:
                    self.fail(f"{command_name} --dry-run should not fail for a known source: {exc}")

        if not checked_commands:
            self.skipTest("memory discovery/ingestion commands are not implemented yet")


class MemoryDocumentIngestionPipelineTests(MemoryModelFactoryMixin, TestCase):
    databases = RUNTIME_DATABASES

    def test_disabled_source_rejects_discovery_and_ingestion_without_writes(self):
        from ..document_ingestion import discover_source_objects, ingest_source_objects, prepare_bootstrap_package

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "disabled_docs"
            root.mkdir()
            (root / "blocked.txt").write_text("must not be discovered", encoding="utf-8")
            source = self.create_source(
                code="disabled_discovery_ingestion",
                source_kind="local_path",
                domain="docs",
                config={
                    "source_ref": str(root),
                    "ignore_patterns": [],
                    "ingestion_profile": "corporate_docs_windows_v1",
                },
            )
            source.status = MemorySource.Status.DISABLED
            source.save(update_fields=["status", "updated_at"])

            with self.assertRaises(ValidationError):
                discover_source_objects(source=source, dry_run=False)
            with self.assertRaises(ValidationError):
                ingest_source_objects(source=source, dry_run=False)
            with self.assertRaises(ValidationError):
                prepare_bootstrap_package(source=source, department="blocked", dry_run=False)
            with self.assertRaises(ValidationError):
                call_command("memory_reindex", source_code=source.code, corpus="source_data", dry_run=True)

            self.assertFalse(MemorySourceObject.objects.filter(source=source).exists())
            self.assertFalse(MemoryIngestionRun.objects.filter(source=source).exists())
            self.assertFalse(MemoryExternalConnectorJob.objects.filter(source_code=source.code).exists())

    def test_discover_source_objects_creates_durable_file_state(self):
        from ..document_ingestion import discover_source_objects

        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            root = Path(tmpdir) / "memory_docs"
            root.mkdir()
            (root / "procedure.txt").write_text("Procedure calibration device_alpha -> procedure_beta", encoding="utf-8")
            source = self.create_source(
                code="local_docs_discovery",
                source_kind="local_path",
                domain="docs",
                scope_rule="authenticated_user",
                config={
                    "source_ref": str(root),
                    "ignore_patterns": [],
                    "ingestion_profile": "corporate_docs_windows_v1",
                },
            )

            metrics = discover_source_objects(source=source, dry_run=False)

            self.assertEqual(metrics["seen"], 1)
            source_object = MemorySourceObject.objects.get(source=source)
            self.assertEqual(source_object.relative_path, "procedure.txt")
            self.assertEqual(source_object.extension, ".txt")
            self.assertEqual(source_object.ingestion_status, MemorySourceObject.IngestionStatus.PENDING)
            self.assertTrue(source_object.content_hash)

    def test_ingest_source_objects_writes_search_document(self):
        from ..document_ingestion import discover_source_objects, ingest_source_objects

        with TemporaryDirectory() as tmpdir:
            Group.objects.get_or_create(name="docs-readers")
            data_dir = Path(tmpdir) / "data"
            root = Path(tmpdir) / "memory_docs"
            root.mkdir()
            (root / "procedure.txt").write_text("Procedure calibration device_alpha -> procedure_beta", encoding="utf-8")
            source = self.create_source(
                code="local_docs_ingestion",
                source_kind="local_path",
                domain="docs",
                scope_rule="authenticated_user",
                config={
                    "source_ref": str(root),
                    "ignore_patterns": [],
                    "ingestion_profile": "corporate_docs_windows_v1",
                    "default_acl": {
                        "allow": [
                            {"kind": "group", "name": "docs-readers"},
                        ]
                    },
                },
            )

            with self.settings(DATA_DIR=data_dir):
                discover_source_objects(source=source, dry_run=False)
                metrics = ingest_source_objects(source=source, dry_run=False)

            source_object = MemorySourceObject.objects.get(source=source)
            self.assertEqual(metrics["ingested"], 1)
            self.assertEqual(source_object.ingestion_status, MemorySourceObject.IngestionStatus.INGESTED)
            document = MemorySearchDocument.objects.get(source_object__source=source, source_object=source_object)
            self.assertEqual(document.corpus_type, MemorySearchDocument.CorpusType.SOURCE_DATA)
            self.assertEqual(document.index_status, MemorySearchDocument.IndexStatus.READY)

    def test_ingest_source_objects_creates_issue_for_unsupported_binary(self):
        from ..document_ingestion import discover_source_objects, ingest_source_objects

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "memory_docs"
            root.mkdir()
            (root / "archive.bin").write_bytes(b"\x00\x01unsupported")
            source = self.create_source(
                code="local_docs_issue",
                source_kind="local_path",
                domain="docs",
                scope_rule="authenticated_user",
                config={
                    "source_ref": str(root),
                    "ignore_patterns": [],
                    "ingestion_profile": "corporate_docs_windows_v1",
                },
            )

            discover_source_objects(source=source, dry_run=False)
            metrics = ingest_source_objects(source=source, dry_run=False)

            self.assertEqual(metrics["issues"], 1)
            issue = MemoryIngestionIssue.objects.get(source=source)
            self.assertEqual(issue.issue_kind, MemoryIngestionIssue.IssueKind.UNSUPPORTED_FORMAT)
            self.assertEqual(issue.status, MemoryIngestionIssue.Status.OPEN)

    def test_ingest_source_objects_blocks_secret_and_audits_pii(self):
        from ..document_ingestion import discover_source_objects, ingest_source_objects
        from ..vector_backends import get_default_backend

        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            root = Path(tmpdir) / "memory_docs"
            root.mkdir()
            (root / "secret.txt").write_text("api_key=sk-test-secret-value-1234567890", encoding="utf-8")
            (root / "pii.txt").write_text("Контакт audit-person@example.com для проверки.", encoding="utf-8")
            source = self.create_source(
                code="local_docs_privacy_gate",
                source_kind="local_path",
                domain="docs",
                scope_rule="authenticated_user",
                trust_status=MemorySource.TrustStatus.TRUSTED,
                authority_class=MemorySource.AuthorityClass.APPROVED_CORPUS,
                trusted_for_context=True,
                requires_source_review=False,
                trusted_context_kinds=["retrieved_chunk", "citation"],
                config={
                    "source_ref": str(root),
                    "ignore_patterns": [],
                    "ingestion_profile": "corporate_docs_windows_v1",
                    "default_acl": {"allow": [{"kind": "group", "name": "privacy-readers"}]},
                },
            )
            Group.objects.create(name="privacy-readers")

            with self.settings(DATA_DIR=data_dir):
                discover_source_objects(source=source, dry_run=False)
                metrics = ingest_source_objects(source=source, dry_run=False)
                pii_index_results = get_default_backend().search(
                    "audit person",
                    scope_tokens=["group:privacy-readers"],
                    sensitivity="internal",
                    limit=5,
                )

            self.assertEqual(metrics["issues"], 2)
            self.assertEqual(metrics["ingested"], 1)
            secret_object = MemorySourceObject.objects.get(source=source, file_name="secret.txt")
            pii_object = MemorySourceObject.objects.get(source=source, file_name="pii.txt")
            self.assertEqual(secret_object.ingestion_status, MemorySourceObject.IngestionStatus.FAILED)
            self.assertEqual(pii_object.ingestion_status, MemorySourceObject.IngestionStatus.INGESTED)
            self.assertFalse(MemorySearchDocument.objects.filter(source_object=secret_object).exists())
            pii_document = MemorySearchDocument.objects.get(source_object=pii_object, index_status=MemorySearchDocument.IndexStatus.READY)
            secret_issue = MemoryIngestionIssue.objects.get(source_object=secret_object)
            pii_issue = MemoryIngestionIssue.objects.get(source_object=pii_object)
            self.assertEqual(secret_issue.issue_kind, MemoryIngestionIssue.IssueKind.SECRET_BLOCKED)
            self.assertEqual(secret_issue.severity, MemoryIngestionIssue.Severity.BLOCKER)
            self.assertEqual(pii_issue.issue_kind, MemoryIngestionIssue.IssueKind.PII_AUDIT)
            self.assertEqual(pii_issue.severity, MemoryIngestionIssue.Severity.WARNING)
            self.assertNotIn("audit-person@example.com", json.dumps(pii_issue.metadata, ensure_ascii=False))
            self.assertIn(pii_document.document_id, {item.document_id for item in pii_index_results})

    def test_inherited_acl_maps_group_to_scope_tokens(self):
        from ..document_ingestion import discover_source_objects, ingest_source_objects

        Group.objects.create(name="docs-readers")
        profiles = _memory_ingestion_profiles_with_acl(
            acl_mode="inherit_source_acl",
            unresolved_policy="block",
        )
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            root = Path(tmpdir) / "memory_docs"
            root.mkdir()
            (root / "procedure.txt").write_text("Procedure calibration device_alpha -> procedure_beta", encoding="utf-8")
            source = self.create_source(
                code="local_docs_acl_allowed",
                source_kind="local_path",
                domain="docs",
                scope_rule="authenticated_user",
                config={
                    "source_ref": str(root),
                    "ignore_patterns": [],
                    "ingestion_profile": "corporate_docs_acl_test_v1",
                    "default_acl": {
                        "allow": [
                            {"kind": "group", "name": "docs-readers"},
                        ]
                    },
                },
            )

            with self.settings(DATA_DIR=data_dir, LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES=profiles):
                discover_source_objects(source=source, dry_run=False)
                metrics = ingest_source_objects(source=source, dry_run=False)

            self.assertEqual(metrics["ingested"], 1)
            document = MemorySearchDocument.objects.get(source_object__source=source)
        self.assertEqual((document.source_object.metadata or {}).get("scope_tokens"), ["group:docs-readers"])

    def test_inherited_acl_unknown_principal_fails_closed(self):
        from ..document_ingestion import discover_source_objects, ingest_source_objects

        profiles = _memory_ingestion_profiles_with_acl(
            acl_mode="inherit_source_acl",
            unresolved_policy="block",
        )
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "memory_docs"
            root.mkdir()
            (root / "procedure.txt").write_text("Procedure calibration device_alpha -> procedure_beta", encoding="utf-8")
            source = self.create_source(
                code="local_docs_acl_blocked",
                source_kind="local_path",
                domain="docs",
                scope_rule="authenticated_user",
                config={
                    "source_ref": str(root),
                    "ignore_patterns": [],
                    "ingestion_profile": "corporate_docs_acl_test_v1",
                    "default_acl": {
                        "allow": [
                            {"kind": "group", "name": "unknown-ad-group"},
                        ]
                    },
                },
            )

            with self.settings(LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES=profiles):
                discover_source_objects(source=source, dry_run=False)
                metrics = ingest_source_objects(source=source, dry_run=False)

            self.assertEqual(metrics["issues"], 1)
            self.assertEqual(MemorySearchDocument.objects.filter(source_object__source=source).count(), 0)
            issue = MemoryIngestionIssue.objects.get(source=source)
            self.assertEqual(issue.issue_kind, MemoryIngestionIssue.IssueKind.ACL_UNRESOLVED)
            self.assertEqual(issue.severity, MemoryIngestionIssue.Severity.BLOCKER)

    def test_discovery_persists_effective_acl_policy_for_root_only_or_block(self):
        from ..document_ingestion import discover_source_objects

        root_actor = User.objects.create_superuser(username="acl-policy-root", password="pass")
        operator = User.objects.create_user(username="acl-policy-operator", password="pass")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "memory_docs"
            root.mkdir()
            (root / "procedure.txt").write_text("Procedure text", encoding="utf-8")

            def create_source(code):
                return self.create_source(
                    code=code,
                    source_kind="local_path",
                    domain="docs",
                    scope_rule="authenticated_user",
                    config={
                        "source_ref": str(root),
                        "ignore_patterns": [],
                        "ingestion_profile": "corporate_docs_acl_test_v1",
                        "default_acl": {"allow": [{"kind": "group", "name": "unknown-ad-group"}]},
                    },
                )

            admin_profiles = _memory_ingestion_profiles_with_acl(
                acl_mode="inherit_source_acl", unresolved_policy="admin_only"
            )
            admin_source = create_source("acl-policy-admin")
            with self.settings(LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES=admin_profiles):
                discover_source_objects(source=admin_source, dry_run=False)
            admin_object = MemorySourceObject.objects.get(source=admin_source)
            self.assertEqual((admin_object.metadata.get("acl") or {}).get("unresolved_policy"), "admin_only")
            self.assertTrue(can_access_source_object(root_actor, admin_object))
            self.assertFalse(can_access_source_object(operator, admin_object))

            # Legacy objects did not persist the effective policy.  Resolve
            # it from the source's configured ingestion profile instead of
            # silently changing admin_only to the global default.
            legacy_acl = dict(admin_object.metadata.get("acl") or {})
            legacy_acl.pop("unresolved_policy", None)
            admin_object.metadata = {**admin_object.metadata, "acl": legacy_acl}
            admin_object.save(update_fields=["metadata", "updated_at"])
            with self.settings(LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES=admin_profiles):
                self.assertTrue(can_access_source_object(root_actor, admin_object))
                self.assertFalse(can_access_source_object(operator, admin_object))

            block_profiles = _memory_ingestion_profiles_with_acl(
                acl_mode="inherit_source_acl", unresolved_policy="block"
            )
            block_source = create_source("acl-policy-block")
            with self.settings(LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES=block_profiles):
                discover_source_objects(source=block_source, dry_run=False)
            block_object = MemorySourceObject.objects.get(source=block_source)
            self.assertEqual((block_object.metadata.get("acl") or {}).get("unresolved_policy"), "block")
            self.assertFalse(can_access_source_object(root_actor, block_object))
