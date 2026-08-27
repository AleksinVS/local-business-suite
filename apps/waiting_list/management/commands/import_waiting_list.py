"""Импорт листа ожидания из табличного текстового файла."""

from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.waiting_list.data_operations import (
    WaitingListImportError,
    import_waiting_list_rows,
    parse_waiting_list_file,
)
from apps.waiting_list.models import WaitingListEntry


class Command(BaseCommand):
    help = "Загрузить записи листа ожидания из текстовой выгрузки с табуляцией."

    def add_arguments(self, parser):
        parser.add_argument(
            "path",
            nargs="?",
            default="drafts/Выгрузка.txt",
            help="Путь к файлу (по умолчанию drafts/Выгрузка.txt).",
        )
        parser.add_argument(
            "--author",
            required=True,
            help="Логин активного пользователя, от имени которого выполняется импорт.",
        )
        parser.add_argument(
            "--append",
            action="store_true",
            help="Разрешить добавление в непустой лист ожидания.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Проверить файл и показать объём импорта без записи в базу.",
        )
        parser.add_argument(
            "--reconcile-projections",
            action="store_true",
            help="После импорта обновить поисковую и аналитическую проекции.",
        )

    def handle(self, *args, **options):
        path = self._resolve_path(options["path"])
        author = self._resolve_author(options["author"])
        existing = WaitingListEntry.objects.count()
        if existing and not options["append"] and not options["dry_run"]:
            raise CommandError(
                f"Лист ожидания уже содержит записей: {existing}. "
                "Сначала выполните clear_waiting_list либо явно передайте --append."
            )

        try:
            rows = parse_waiting_list_file(path)
        except WaitingListImportError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"Файл: {path}")
        self.stdout.write(f"Проверено строк: {len(rows)}")
        if options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(
                    "Предварительная проверка завершена; база не изменена."
                )
            )
            return

        try:
            created, audit_created = import_waiting_list_rows(rows, author=author)
        except WaitingListImportError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Импорт завершён: записей={created}, событий журнала={audit_created}."
            )
        )
        if options["reconcile_projections"]:
            call_command(
                "source_adapter_reconcile",
                source_code="waiting_list",
                target="all",
                backend="all",
                stdout=self.stdout,
                stderr=self.stderr,
            )

    @staticmethod
    def _resolve_path(raw_path: str) -> Path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        if not path.is_file():
            raise CommandError(f"Файл не найден: {path}")
        return path

    @staticmethod
    def _resolve_author(raw_author: str):
        user_model = get_user_model()
        username_field = user_model.USERNAME_FIELD
        author = user_model.objects.filter(
            **{username_field: raw_author, "is_active": True}
        ).first()
        if author is None:
            raise CommandError(
                f"Активный пользователь с {username_field}={raw_author!r} не найден."
            )
        return author
