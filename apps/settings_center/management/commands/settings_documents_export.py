"""Export effective runtime document and its integrity manifest."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.settings_center.document_migration import (
    _assert_safe_existing_directory,
    _assert_safe_output,
    export_document,
)


class Command(BaseCommand):
    help = "Экспортировать effective database_override документ и manifest."

    def add_arguments(self, parser):
        parser.add_argument("--document-id", required=True)
        parser.add_argument("--output", required=True)
        parser.add_argument("--manifest")
        parser.add_argument(
            "--operator-output-root",
            help="Существующий защищённый каталог для вывода вне .local.",
        )

    def handle(self, *args, **options):
        output = Path(options["output"])
        manifest = Path(options["manifest"]) if options.get("manifest") else None
        try:
            output = _assert_safe_output(output, local_only=False)
            manifest = _assert_safe_output(
                manifest or output.with_suffix(".manifest.json"), local_only=False
            )
            local_root = Path(settings.BASE_DIR) / ".local"
            try:
                output.relative_to(local_root.resolve())
                manifest_is_local = manifest.relative_to(local_root.resolve()) is not None
                output_is_local = True and manifest_is_local
            except ValueError:
                output_is_local = False
            if not output_is_local:
                if not options.get("operator_output_root"):
                    raise CommandError(
                        "Вывод вне .local требует --operator-output-root."
                    )
                root = _assert_safe_existing_directory(
                    Path(options["operator_output_root"])
                )
                try:
                    output.relative_to(root)
                    manifest.relative_to(root)
                except ValueError as exc:
                    raise CommandError(
                        "Файлы экспорта должны находиться внутри --operator-output-root."
                    ) from exc
            result = export_document(
                options["document_id"],
                output=output,
                manifest_output=manifest,
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            "Экспортирован {document_id}: {output}; manifest={manifest}; "
            "source={source}; revision={revision}; hash={content_hash}".format(**result)
        )
