"""Импорт медицинских изделий из выгрузки ФРМО (Excel).

Алгоритм:
1. Прочитать все строки Excel в память.
2. Для каждой строки распарсить поля и резолвить подразделение
   (по имени, через словарь; пустое имя → подразделение-агрегатор).
3. Сгруппировать строки по merge-ключу: все поля кроме здания/этажа/кабинета.
   Строки в одной группе считаются одним и тем же изделием, указанным
   в разных корпусах/этажах/кабинетах.
4. Для каждой группы собрать «адрес» — конкатенация строк вида
   «Здание - Этаж - Кабинет» (через «; ») по всем строкам группы.
5. Если один и тот же ``inventory_number`` встречается в нескольких
   merge-группах — все такие группы пропускаются, а исходные строки
   Excel пишутся в ``--csv-path`` с причиной ``duplicate_inventory_conflict``.
6. Для неконфликтных групп — ``update_or_create`` по ``inventory_number``.

Пример запуска::

    python manage.py import_frmo_devices --dry-run
    python manage.py import_frmo_devices
    python manage.py import_frmo_devices --csv-path data/dupes.csv --update-existing
"""

from __future__ import annotations

import csv
import datetime as dt
from collections import defaultdict
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from python_calamine import CalamineWorkbook

from apps.core.models import Department
from apps.inventory.models import MedicalDevice, OperationalStatus


# Подразделение-агрегатор: используется для строк, у которых колонка
# «Структурное подразделение» пуста. Имя совпадает с data-миграцией
# 0007_catchall_department.
CATCHALL_DEPARTMENT_NAME = "Вологодская областная больница №3"


# Заголовок Excel → поле MedicalDevice. Ключ "_department_name" — служебный:
# значение не пишется в модель, а используется для резолва FK Department.
HEADER_FIELDS: dict[str, str] = {
    "Дата регистрации": "registration_date",
    "Номер регистрационного удостоверения": "registration_certificate_number",
    "Наименование": "name",
    "Тип медицинского изделия": "device_type",
    "Производитель": "manufacturer",
    "Страна производства": "production_country",
    "Модель": "model",
    "Серийный номер": "serial_number",
    "Инвентарный номер": "inventory_number",
    "Дата выпуска": "production_date",
    "Дата ввода в эксплуатацию": "commissioned_at",
    "Срок службы/ годности, лет": "service_life_years",
    "Дата вывода из эксплуатации": "decommissioned_at",
    "Причина вывода": "decommission_reason",
    "Структурное подразделение": "_department_name",
}

# Колонки исходного Excel, которые нужны для построения «адреса».
# Они НЕ кладутся в payload модели — используются только для склейки.
ADDRESS_COLUMNS: tuple[str, ...] = ("Здание", "Этаж", "Кабинет")


_DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d.%m.%Y %H:%M:%S",
)


def _normalize_dept_name(value: object) -> str:
    """Нормализовать имя подразделения для поиска: strip + collapse пробелов."""
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _to_date(value: object) -> dt.date | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"не удалось разобрать дату: {text!r}")


def _to_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    return int(float(text))


def _to_str(value: object) -> str:
    """Строковое представление ячейки Excel.

    Особенности:
    - ``None`` / пустая строка → пустая строка.
    - ``float`` с дробной частью ``0`` (например, ``1.0`` от calamine) →
      целое ``"1"``. Нужно, чтобы этаж/кабинет не печатались как ``"1.0"``.
    - ``bool`` → ``"True"``/``"False"`` через стандартный ``str``.
    """
    if value is None:
        return ""
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    text = str(value).strip()
    return text


class Command(BaseCommand):
    help = "Импорт медицинских изделий из выгрузки ФРМО (Excel)."

    def add_arguments(self, parser):
        parser.add_argument(
            "path",
            nargs="?",
            default=".local/Оборудование из ФРМО.xlsx",
            help="Путь к Excel-файлу (по умолчанию .local/Оборудование из ФРМО.xlsx)",
        )
        parser.add_argument(
            "--sheet",
            default="0",
            help="Имя листа или его индекс (по умолчанию 0 — первый лист)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Только показать план импорта, в БД ничего не писать.",
        )
        parser.add_argument(
            "--update-existing",
            action="store_true",
            help=(
                "Обновлять существующие записи по инвентарному номеру. "
                "По умолчанию (без флага) строки с уже известным "
                "inventory_number пропускаются."
            ),
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Удалить все существующие MedicalDevice перед импортом (опасно).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Обработать только N первых строк (0 — без ограничения).",
        )
        parser.add_argument(
            "--unknown-department",
            default=CATCHALL_DEPARTMENT_NAME,
            help=(
                "Имя подразделения-агрегатора для строк без «Структурного "
                "подразделения». По умолчанию «Вологодская областная больница "
                "№3» (создаётся миграцией 0007). Пустая строка — отключить агрегатор."
            ),
        )
        parser.add_argument(
            "--no-create-unknown",
            action="store_true",
            help=(
                "Не создавать подразделение-агрегатор, если его нет в БД. "
                "Полезно для CI: падать с понятной ошибкой."
            ),
        )
        parser.add_argument(
            "--csv-path",
            default=".local/frmo_duplicates.csv",
            help=(
                "Путь к CSV-файлу для строк, не прошедших merge-логику "
                "(по умолчанию .local/frmo_duplicates.csv). "
                "Можно передать пустую строку, чтобы отключить запись CSV."
            ),
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Прервать импорт на первой незапланированной ошибке.",
        )

    # ------------------------------------------------------------------ helpers

    def _resolve_path(self, raw: str) -> Path:
        path = Path(raw)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / raw
        if not path.exists():
            raise CommandError(f"Файл не найден: {path}")
        return path

    def _resolve_sheet(self, wb: CalamineWorkbook, raw: str):
        if raw.isdigit():
            index = int(raw)
            if index < 0 or index >= len(wb.sheet_names):
                raise CommandError(
                    f"Лист с индексом {index} отсутствует. Доступно: {wb.sheet_names}"
                )
            return wb.get_sheet_by_index(index)
        if raw not in wb.sheet_names:
            raise CommandError(
                f"Лист {raw!r} не найден. Доступно: {wb.sheet_names}"
            )
        return wb.get_sheet_by_name(raw)

    def _build_dept_index(
        self, catchall_name: str, allow_create: bool
    ) -> tuple[dict[str, Department], Department | None]:
        index: dict[str, Department] = {}
        catchall: Department | None = None
        for dept in Department.objects.all():
            key = _normalize_dept_name(dept.name)
            if not key:
                continue
            index.setdefault(key.lower(), dept)

        if catchall_name:
            catchall_key = _normalize_dept_name(catchall_name).lower()
            catchall = index.get(catchall_key)
            if catchall is None:
                if not allow_create:
                    raise CommandError(
                        f"Подразделение-агрегатор {catchall_name!r} не найдено в БД. "
                        "Запустите миграцию 0007 или передайте --no-create-unknown=false."
                    )
                catchall = Department.objects.create(
                    name=_normalize_dept_name(catchall_name),
                    parent=None,
                )
                index[catchall_key] = catchall
                self.stdout.write(
                    self.style.WARNING(
                        f"Создан агрегатор {catchall_name!r} (id={catchall.id})"
                    )
                )

        self.stdout.write(f"Загружено подразделений из БД: {len(index)}")
        return index, catchall

    @staticmethod
    def _row_to_payload(
        row: list[object],
        col_index: dict[str, int],
        dept_index: dict[str, Department],
        catchall: Department | None,
    ) -> tuple[dict, str | None, str | None]:
        payload: dict = {}
        try:
            for header, field in HEADER_FIELDS.items():
                idx = col_index.get(header)
                if idx is None or idx >= len(row):
                    continue
                value = row[idx]
                if field == "_department_name":
                    payload["_department_name"] = _to_str(value)
                elif field in {
                    "registration_date",
                    "production_date",
                    "commissioned_at",
                    "decommissioned_at",
                }:
                    payload[field] = _to_date(value)
                elif field == "service_life_years":
                    payload[field] = _to_int(value)
                else:
                    payload[field] = _to_str(value)
        except ValueError as exc:
            return {}, f"ошибка разбора значения: {exc}", None

        # ``serial_number`` теперь опциональный — пустое значение допустимо.
        serial = payload.get("serial_number", "")
        name = payload.get("name", "")
        inventory = payload.get("inventory_number", "")
        dept_key = _normalize_dept_name(payload.get("_department_name", ""))

        if not serial and not name and not inventory:
            return {}, None, "пустая строка"
        if not name:
            return {}, "не указано наименование", None
        if not inventory:
            return {}, "не указан инвентарный номер", None

        if dept_key:
            department = dept_index.get(dept_key.lower())
            if department is None:
                return (
                    {},
                    f"подразделение не найдено в БД: {payload['_department_name']!r}",
                    None,
                )
        elif catchall is not None:
            department = catchall
        else:
            return {}, "не указано структурное подразделение", None

        payload["department"] = department
        payload["department_id"] = department.id
        payload.pop("_department_name", None)

        if payload.get("decommissioned_at"):
            payload.setdefault("operational_status", OperationalStatus.DECOMMISSIONED)
        else:
            payload.setdefault("operational_status", OperationalStatus.ACTIVE)

        return payload, None, None

    @staticmethod
    def _merge_key(payload: dict) -> tuple:
        """Ключ слияния: все поля кроме building/floor/room (которых в payload нет).

        Внутри группы все значения одинаковы → один ``MedicalDevice``,
        а отличия в building/floor/room собираются в ``address``.
        """
        return (
            payload.get("registration_date"),
            payload.get("registration_certificate_number"),
            payload.get("name"),
            payload.get("device_type"),
            payload.get("manufacturer"),
            payload.get("production_country"),
            payload.get("model"),
            payload.get("serial_number"),
            payload.get("inventory_number"),
            payload.get("production_date"),
            payload.get("commissioned_at"),
            payload.get("service_life_years"),
            payload.get("decommissioned_at"),
            payload.get("decommission_reason"),
            payload.get("department_id"),
        )

    @staticmethod
    def _build_address(row: list[object], col_index: dict[str, int]) -> str:
        parts: list[str] = []
        for header in ADDRESS_COLUMNS:
            idx = col_index.get(header)
            if idx is None or idx >= len(row):
                continue
            text = _to_str(row[idx])
            if text:
                parts.append(text)
        if not parts:
            return ""
        return " - ".join(parts)

    @staticmethod
    def _row_as_list(row: list[object], header: list[str]) -> list[str]:
        """Преобразовать сырую строку в список строк той же длины, что и шапка."""
        result: list[str] = []
        for i in range(len(header)):
            if i < len(row) and row[i] is not None:
                result.append(str(row[i]))
            else:
                result.append("")
        return result

    # ------------------------------------------------------------------ main

    @transaction.atomic
    def handle(self, *args, **options):
        path = self._resolve_path(options["path"])
        self.stdout.write(f"Файл-источник: {path}")

        wb = CalamineWorkbook.from_path(str(path))
        sheet = self._resolve_sheet(wb, str(options["sheet"]))
        rows = sheet.to_python()
        if not rows:
            raise CommandError("Файл не содержит строк.")

        header = [str(c).strip() if c is not None else "" for c in rows[0]]
        col_index = {name: idx for idx, name in enumerate(header)}

        required_headers = list(HEADER_FIELDS.keys()) + list(ADDRESS_COLUMNS)
        missing_headers = [h for h in required_headers if h not in col_index]
        if missing_headers:
            raise CommandError(
                "В файле отсутствуют обязательные колонки: "
                + ", ".join(repr(h) for h in missing_headers)
            )

        if options["clear"] and not options["dry_run"]:
            deleted, _ = MedicalDevice.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Удалено изделий: {deleted}"))

        catchall_name = (options.get("unknown_department") or "").strip()
        dept_index, catchall = self._build_dept_index(
            catchall_name=catchall_name,
            allow_create=not options["no_create_unknown"],
        )

        data_rows = rows[1:]
        if options["limit"]:
            data_rows = data_rows[: options["limit"]]

        # ---- Шаг 1: парсинг всех строк ---------------------------------
        parsed: list[tuple[int, list[object], dict]] = []
        parse_errors = 0
        empty_rows = 0
        catchall_used = 0
        parse_error_samples: list[str] = []

        for row_no, row in enumerate(data_rows, start=2):
            payload, error, skip_reason = self._row_to_payload(
                row, col_index, dept_index, catchall
            )
            if skip_reason is not None:
                empty_rows += 1
                continue
            if error is not None:
                parse_errors += 1
                msg = f"строка {row_no}: {error}"
                parse_error_samples.append(msg)
                self.stdout.write(self.style.WARNING(msg))
                if options["strict"]:
                    raise CommandError(f"Прервано в --strict на {msg}")
                continue
            if (
                catchall is not None
                and payload.get("department_id") == catchall.id
            ):
                catchall_used += 1
            parsed.append((row_no, row, payload))

        # ---- Шаг 2: группировка ----------------------------------------
        groups: dict[tuple, list[tuple[int, list[object], dict]]] = defaultdict(list)
        for row_no, row, payload in parsed:
            groups[self._merge_key(payload)].append((row_no, row, payload))

        # ---- Шаг 3: конфликты по inventory_number ----------------------
        inv_to_keys: dict[str, list[tuple]] = defaultdict(list)
        for key, group in groups.items():
            inv = group[0][2].get("inventory_number", "")
            inv_to_keys[inv].append(key)
        conflicting_keys = {
            key for inv, ks in inv_to_keys.items() if len(ks) > 1 for key in ks
        }
        conflict_groups = sum(1 for k in groups if k in conflicting_keys)

        # Собираем CSV-строки для конфликтных групп.
        csv_rows: list[tuple[int, list[object], str]] = []
        for key in conflicting_keys:
            for row_no, row, _ in groups[key]:
                csv_rows.append((row_no, row, "duplicate_inventory_conflict"))

        # ---- Шаг 4: запись неконфликтных групп ------------------------
        created = updated = skipped_existing = 0
        write_errors = 0
        write_error_samples: list[str] = []

        for key, group in groups.items():
            if key in conflicting_keys:
                continue
            base_rn, base_row, base_payload = group[0]

            # Собираем «адрес» по всем строкам группы (с дедупликацией).
            addresses: list[str] = []
            for _, r, _ in group:
                addr = self._build_address(r, col_index)
                if addr:
                    addresses.append(addr)
            base_payload["address"] = "; ".join(dict.fromkeys(addresses))

            if options["dry_run"]:
                # В dry-run считаем «создано/обновлено» по наличию записи в БД.
                exists = MedicalDevice.objects.filter(
                    inventory_number=base_payload["inventory_number"]
                ).exists()
                if not exists:
                    created += 1
                elif options["update_existing"]:
                    updated += 1
                else:
                    skipped_existing += 1
                continue

            if not options["update_existing"]:
                existing = (
                    MedicalDevice.objects.filter(
                        inventory_number=base_payload["inventory_number"]
                    )
                    .only("id")
                    .first()
                )
                if existing is not None:
                    skipped_existing += 1
                    continue

            try:
                _, is_created = MedicalDevice.objects.update_or_create(
                    inventory_number=base_payload["inventory_number"],
                    defaults=base_payload,
                )
            except Exception as exc:
                write_errors += 1
                msg = (
                    f"строка {base_rn}: ошибка записи "
                    f"({exc.__class__.__name__}): {exc}"
                )
                write_error_samples.append(msg)
                self.stdout.write(self.style.WARNING(msg))
                if options["strict"]:
                    raise CommandError(f"Прервано в --strict: {msg}")
                continue

            if is_created:
                created += 1
            else:
                updated += 1

        # ---- Шаг 5: запись CSV -----------------------------------------
        csv_path = (options.get("csv_path") or "").strip()
        if csv_rows and csv_path:
            csv_file = Path(csv_path)
            if not csv_file.is_absolute():
                csv_file = Path(settings.BASE_DIR) / csv_path
            csv_file.parent.mkdir(parents=True, exist_ok=True)
            # utf-8-sig — BOM, чтобы Excel открыл без танцев с кодировкой.
            with csv_file.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["row_no", *header, "reason"])
                for row_no, row, reason in csv_rows:
                    writer.writerow([row_no, *self._row_as_list(row, header), reason])
            self.stdout.write(
                self.style.WARNING(
                    f"Записано в CSV: {len(csv_rows)} строк → {csv_file}"
                )
            )

        # ---- Сводка ---------------------------------------------------
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Импорт завершён."))
        self.stdout.write(f"  Создано:        {created}")
        self.stdout.write(f"  Обновлено:      {updated}")
        self.stdout.write(f"  Пропущено:      {skipped_existing} (уже в БД, без --update-existing)")
        self.stdout.write(f"  Пустых строк:   {empty_rows}")
        self.stdout.write(f"  Ошибок разбора: {parse_errors}")
        self.stdout.write(f"  Merge-групп:    {len(groups)}")
        if conflicting_keys:
            self.stdout.write(
                self.style.WARNING(
                    f"  Конфликтов:     {conflict_groups} "
                    "(групп с дублирующимся inventory_number)"
                )
            )
            self.stdout.write(
                f"  В CSV:          {len(csv_rows)} "
                "(строк, по причине duplicate_inventory_conflict)"
            )
        if catchall_used:
            self.stdout.write(
                f"  Агрегатор:      {catchall_used} "
                f"(подразделение-приёмник «{catchall_name}»)"
            )
        if write_errors:
            self.stdout.write(f"  Ошибок записи:  {write_errors}")

        if parse_error_samples or write_error_samples:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Примеры ошибок:"))
            for msg in (parse_error_samples + write_error_samples)[:10]:
                self.stdout.write(f"  {msg}")