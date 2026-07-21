"""Идемпотентное наполнение портала демонстрационными данными для ручного тестирования UI.

В отличие от ``seed_hospital_demo`` (небольшой фиксированный референсный набор),
эта команда создает более широкий и разнообразный русскоязычный демо-датасет:
подразделения, пользователей с известными паролями под все три роли из
``contracts/role_rules.json``, медицинские изделия, заявки во всех статусах и
приоритетах, а также записи листа ожидания.

Идемпотентность
----------------
Все объекты создаются/обновляются через ``get_or_create``/``update_or_create``
по стабильным естественным ключам (имя пользователя, инвентарный номер,
заголовок заявки, пара ФИО+телефон пациента и т. п.), поэтому повторный запуск
не создает дублей.

Маркировка демо-объектов
-------------------------
Все созданные этой командой объекты помечены и могут быть безопасно найдены и
удалены:

- пользователи — имя пользователя с префиксом ``demo_``;
- подразделения — имя с префиксом ``[demo] `` (создаются как дочерние по
  отношению к существующему подразделению-агрегатору «Вологодская областная
  больница №3», которое само не трогается);
- медицинские изделия — инвентарный номер с префиксом ``DEMO-`` и заметка,
  начинающаяся с ``[demo]``;
- канбан-доска — слаг ``demo-portal``;
- заявки — заголовок с префиксом ``[demo] `` и описание, начинающееся с ``[demo]``;
- записи листа ожидания — комментарий, начинающийся с ``[demo]``.

Флаг ``--flush`` удаляет все ранее созданные демо-объекты (по перечисленным
маркерам) перед повторным наполнением — полезно, чтобы отчистить датасет от
устаревших вариантов после правки этого файла.

Пример запуска::

    python manage.py seed_demo_data
    python manage.py seed_demo_data --flush
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core.contract_store import get_contract
from apps.core.models import Department
from apps.inventory.models import MedicalDevice, OperationalStatus
from apps.waiting_list.models import WaitingListEntry, WaitingListStatus
from apps.workorders.models import Board, WorkOrder, WorkOrderPriority, WorkOrderStatus

User = get_user_model()

DEMO_MARKER = "[demo]"
DEMO_USERNAME_PREFIX = "demo_"
DEMO_INVENTORY_PREFIX = "DEMO-"
DEMO_BOARD_SLUG = "demo-portal"
DEMO_EMAIL_DOMAIN = "demo.portal.local"
DEMO_PASSWORD = "DemoPortal-2026!"

# Должно совпадать с data-миграцией apps/inventory/migrations/0007_catchall_department.py
# и apps/inventory/forms.py / apps/inventory/management/commands/import_frmo_devices.py.
CATCHALL_DEPARTMENT_NAME = "Вологодская областная больница №3"

ROLE_NAMES = ("customer", "technician", "manager")

DEFAULT_COLUMNS = [
    ("new", "Новые", 10, ["new"]),
    ("in_progress", "В работе", 20, ["accepted", "in_progress", "on_hold"]),
    ("done", "Выполнены", 30, ["resolved"]),
    ("archive", "Архив", 40, ["closed", "cancelled"]),
]

# Дочерние подразделения демо-иерархии: (ключ, короткое имя, ключ родителя или None для катчолла).
DEPARTMENT_SPECS = [
    ("reanim", "Отделение реанимации", None),
    ("surgery", "Хирургическое отделение", None),
    ("therapy", "Терапевтическое отделение", None),
    ("admission", "Приемное отделение", None),
    ("diagnostics", "Отделение диагностики", None),
    ("uzi", "Кабинет УЗИ", "diagnostics"),
    ("lab", "Лаборатория", "diagnostics"),
]

# (ключ, суффикс username, имя, фамилия, роль, ключ подразделения или None, is_staff)
USER_SPECS = [
    ("mgr1", "manager1", "Ольга", "Смирнова", "manager", None, True),
    ("mgr2", "manager2", "Дмитрий", "Ковалёв", "manager", None, True),
    ("tech1", "tech1", "Иван", "Морозов", "technician", "surgery", False),
    ("tech2", "tech2", "Сергей", "Волков", "technician", "reanim", False),
    ("tech3", "tech3", "Павел", "Никитин", "technician", "diagnostics", False),
    ("cust1", "customer1", "Анна", "Лебедева", "customer", "therapy", False),
    ("cust2", "customer2", "Мария", "Кузнецова", "customer", "admission", False),
    ("cust3", "customer3", "Елена", "Соколова", "customer", "lab", False),
    ("cust4", "customer4", "Наталья", "Волкова", "customer", "uzi", False),
]

# (ключ, наименование, тип изделия, производитель, страна, модель, ключ подразделения,
#  статус эксплуатации, признак списания)
DEVICE_SPECS = [
    ("defib1", "Дефибриллятор Physio-Control LIFEPAK 20", "дефибриллятор", "Physio-Control", "США", "LIFEPAK 20", "reanim", OperationalStatus.ACTIVE, False),
    ("ivl1", "Аппарат ИВЛ Dräger Evita V500", "аппарат искусственной вентиляции легких", "Dräger", "Германия", "Evita V500", "reanim", OperationalStatus.ACTIVE, False),
    ("monitor1", "Монитор пациента Mindray uMEC12", "монитор пациента", "Mindray", "Китай", "uMEC12", "reanim", OperationalStatus.ACTIVE, False),
    ("infusomat1", "Инфузомат B.Braun Perfusor Space", "инфузомат", "B.Braun", "Германия", "Perfusor Space", "reanim", OperationalStatus.MAINTENANCE, False),
    ("ecg1", "Электрокардиограф Schiller CARDIOVIT AT-104", "электрокардиограф", "Schiller", "Швейцария", "CARDIOVIT AT-104", "reanim", OperationalStatus.ACTIVE, False),
    ("anest1", "Наркозно-дыхательный аппарат Dräger Fabius Tiro", "наркозно-дыхательный аппарат", "Dräger", "Германия", "Fabius Tiro", "surgery", OperationalStatus.ACTIVE, False),
    ("electrosurg1", "Электрохирургический аппарат ForceTriad", "электрохирургический аппарат", "Covidien", "США", "ForceTriad", "surgery", OperationalStatus.ACTIVE, False),
    ("sterilizer1", "Стерилизатор паровой ГК-100-3", "стерилизатор", "Тюменский завод медоборудования", "Россия", "ГК-100-3", "surgery", OperationalStatus.ACTIVE, False),
    ("lamp1", "Хирургический светильник Martin MTX", "хирургический светильник", "KLS Martin", "Германия", "MTX", "surgery", OperationalStatus.RESERVED, False),
    ("aspirator1", "Отсасыватель хирургический Armed 7Е-А", "аспиратор хирургический", "Armed", "Россия", "7Е-А", "surgery", OperationalStatus.MAINTENANCE, False),
    ("ecg2", "Электрокардиограф Bionet CardioCare 2000", "электрокардиограф", "Bionet", "Республика Корея", "CardioCare 2000", "therapy", OperationalStatus.ACTIVE, False),
    ("defib2", "Дефибриллятор Zoll AED Plus", "дефибриллятор", "Zoll", "США", "AED Plus", "therapy", OperationalStatus.RESERVED, False),
    ("nebulizer1", "Небулайзер компрессорный OMRON CompAir", "небулайзер", "OMRON", "Япония", "CompAir", "therapy", OperationalStatus.ACTIVE, False),
    ("bed1", "Кровать функциональная медицинская Armed RS105", "кровать функциональная", "Armed", "Россия", "RS105", "therapy", OperationalStatus.DECOMMISSIONED, True),
    ("xray1", "Рентген-аппарат передвижной Shimadzu MobileArt", "рентгеновский аппарат", "Shimadzu", "Япония", "MobileArt", "admission", OperationalStatus.ACTIVE, False),
    ("defib3", "Дефибриллятор Philips HeartStart XL+", "дефибриллятор", "Philips", "Нидерланды", "HeartStart XL+", "admission", OperationalStatus.ACTIVE, False),
    ("pulseox1", "Пульсоксиметр Nonin Onyx Vantage", "пульсоксиметр", "Nonin", "США", "Onyx Vantage", "admission", OperationalStatus.MAINTENANCE, False),
    ("sterilizer2", "Стерилизатор централизованный Tuttnauer 3870EA", "стерилизатор", "Tuttnauer", "Израиль", "3870EA", "diagnostics", OperationalStatus.ACTIVE, False),
    ("usi1", "УЗИ-сканер Mindray DC-70", "УЗИ-сканер", "Mindray", "Китай", "DC-70", "uzi", OperationalStatus.ACTIVE, False),
    ("usi2", "УЗИ-сканер GE Voluson E8", "УЗИ-сканер", "General Electric", "США", "Voluson E8", "uzi", OperationalStatus.MAINTENANCE, False),
    ("usi3", "УЗИ-сканер Samsung HS40", "УЗИ-сканер", "Samsung", "Республика Корея", "HS40", "uzi", OperationalStatus.DECOMMISSIONED, True),
    ("analyzer1", "Биохимический анализатор Mindray BS-240", "лабораторный анализатор", "Mindray", "Китай", "BS-240", "lab", OperationalStatus.ACTIVE, False),
    ("analyzer2", "Гематологический анализатор Sysmex XN-350", "лабораторный анализатор", "Sysmex", "Япония", "XN-350", "lab", OperationalStatus.ACTIVE, False),
    ("centrifuge1", "Центрифуга лабораторная ОПН-8", "центрифуга", "Дастан", "Россия", "ОПН-8", "lab", OperationalStatus.ACTIVE, False),
    ("microscope1", "Микроскоп бинокулярный Levenhuk MED 30T", "микроскоп", "Levenhuk", "США", "MED 30T", "lab", OperationalStatus.RESERVED, False),
    ("autoclave1", "Автоклав лабораторный ГК-25", "стерилизатор", "Тюменский завод медоборудования", "Россия", "ГК-25", "lab", OperationalStatus.DECOMMISSIONED, True),
]

# (номер, ключ подразделения, ключ изделия|None, ключ автора, ключ исполнителя|None,
#  приоритет, статус, дней назад создана, короткий текст)
WORKORDER_SPECS = [
    (1, "reanim", "defib1", "mgr1", "tech2", WorkOrderPriority.CRITICAL, WorkOrderStatus.NEW, 1, "Дефибриллятор LIFEPAK 20 не включается"),
    (2, "reanim", "ivl1", "mgr1", "tech2", WorkOrderPriority.CRITICAL, WorkOrderStatus.IN_PROGRESS, 3, "Аппарат ИВЛ Evita V500 сигнализирует об ошибке давления"),
    (3, "reanim", "monitor1", "mgr1", "tech2", WorkOrderPriority.HIGH, WorkOrderStatus.ACCEPTED, 2, "Монитор пациента uMEC12 не отображает пульс"),
    (4, "reanim", "infusomat1", "mgr1", "tech2", WorkOrderPriority.MEDIUM, WorkOrderStatus.ON_HOLD, 6, "Инфузомат Perfusor Space требует замены аккумулятора"),
    (5, "reanim", "ecg1", "mgr1", "tech2", WorkOrderPriority.MEDIUM, WorkOrderStatus.RESOLVED, 10, "Электрокардиограф CARDIOVIT печатает нечеткую ленту"),
    (6, "reanim", None, "mgr1", "tech2", WorkOrderPriority.LOW, WorkOrderStatus.CLOSED, 20, "Заменить лампу освещения в палате реанимации"),
    (7, "surgery", "anest1", "mgr2", "tech1", WorkOrderPriority.CRITICAL, WorkOrderStatus.IN_PROGRESS, 2, "Наркозно-дыхательный аппарат Fabius Tiro теряет герметичность контура"),
    (8, "surgery", "electrosurg1", "mgr2", "tech1", WorkOrderPriority.HIGH, WorkOrderStatus.ACCEPTED, 4, "Электрохирургический аппарат ForceTriad искрит при работе"),
    (9, "surgery", "sterilizer1", "mgr2", "tech1", WorkOrderPriority.HIGH, WorkOrderStatus.NEW, 1, "Стерилизатор паровой ГК-100-3 не набирает давление"),
    (10, "surgery", "lamp1", "mgr2", "tech1", WorkOrderPriority.LOW, WorkOrderStatus.RESOLVED, 8, "Хирургический светильник MTX мигает"),
    (11, "surgery", "aspirator1", "mgr2", "tech1", WorkOrderPriority.MEDIUM, WorkOrderStatus.ON_HOLD, 5, "Отсасыватель хирургический 7Е-А слабо держит вакуум"),
    (12, "surgery", None, "mgr2", None, WorkOrderPriority.LOW, WorkOrderStatus.CANCELLED, 15, "Проверить розетки в операционной №2"),
    (13, "therapy", "ecg2", "cust1", "tech1", WorkOrderPriority.MEDIUM, WorkOrderStatus.NEW, 1, "Электрокардиограф CardioCare 2000 не заряжается"),
    (14, "therapy", "defib2", "cust1", "tech2", WorkOrderPriority.HIGH, WorkOrderStatus.ACCEPTED, 3, "Дефибриллятор Zoll AED Plus сообщает об ошибке электродов"),
    (15, "therapy", "nebulizer1", "cust1", "tech1", WorkOrderPriority.LOW, WorkOrderStatus.IN_PROGRESS, 2, "Небулайзер CompAir шумит сильнее обычного"),
    (16, "therapy", "bed1", "cust1", "tech1", WorkOrderPriority.MEDIUM, WorkOrderStatus.CLOSED, 25, "Функциональная кровать RS105 не фиксируется в положении"),
    (17, "therapy", None, "cust1", None, WorkOrderPriority.LOW, WorkOrderStatus.NEW, 1, "Заменить кран в процедурном кабинете терапии"),
    (18, "admission", "xray1", "cust2", "tech3", WorkOrderPriority.CRITICAL, WorkOrderStatus.ACCEPTED, 2, "Передвижной рентген-аппарат MobileArt не формирует снимок"),
    (19, "admission", "defib3", "cust2", "tech2", WorkOrderPriority.HIGH, WorkOrderStatus.IN_PROGRESS, 4, "Дефибриллятор HeartStart XL+ разрядился и не заряжается"),
    (20, "admission", "pulseox1", "cust2", "tech3", WorkOrderPriority.LOW, WorkOrderStatus.RESOLVED, 7, "Пульсоксиметр Onyx Vantage показывает нестабильные значения"),
    (21, "admission", None, "cust2", "tech3", WorkOrderPriority.MEDIUM, WorkOrderStatus.ON_HOLD, 6, "Не закрывается дверь приемного покоя"),
    (22, "admission", None, "cust2", None, WorkOrderPriority.LOW, WorkOrderStatus.NEW, 1, "Скрипит кресло-каталка в приемном отделении"),
    (23, "diagnostics", "sterilizer2", "mgr1", "tech3", WorkOrderPriority.MEDIUM, WorkOrderStatus.ACCEPTED, 3, "Централизованный стерилизатор 3870EA долго набирает цикл"),
    (24, "diagnostics", None, "mgr1", "tech3", WorkOrderPriority.LOW, WorkOrderStatus.RESOLVED, 9, "Обновить компьютер в кабинете диагностики"),
    (25, "uzi", "usi1", "cust4", "tech3", WorkOrderPriority.HIGH, WorkOrderStatus.IN_PROGRESS, 2, "УЗИ-сканер Mindray DC-70 теряет изображение с датчика"),
    (26, "uzi", "usi2", "cust4", "tech3", WorkOrderPriority.MEDIUM, WorkOrderStatus.ON_HOLD, 5, "УЗИ-сканер GE Voluson E8 требует калибровки"),
    (27, "uzi", None, "cust4", None, WorkOrderPriority.LOW, WorkOrderStatus.NEW, 1, "Заменить кресло в кабинете УЗИ"),
    (28, "lab", "analyzer1", "cust3", "tech3", WorkOrderPriority.HIGH, WorkOrderStatus.RESOLVED, 11, "Биохимический анализатор BS-240 выдает ошибку реагента"),
    (29, "lab", "analyzer2", "cust3", "tech3", WorkOrderPriority.CRITICAL, WorkOrderStatus.IN_PROGRESS, 2, "Гематологический анализатор Sysmex XN-350 не считывает пробирки"),
    (30, "lab", "centrifuge1", "cust3", "tech3", WorkOrderPriority.MEDIUM, WorkOrderStatus.CANCELLED, 12, "Центрифуга ОПН-8 вибрирует при разгоне — устройство заменено"),
]

# (номер, ФИО, дата рождения, телефон, услуга, дней до целевой даты|None,
#  дней до крайней даты|None, CITO, статус, ключ автора|None)
WAITING_LIST_SPECS = [
    (1, "Смирнова Анна Викторовна", date(1985, 4, 12), "+7 921 555-01-01", "s1", 3, 5, True, WaitingListStatus.WAITING, "cust1"),
    (2, "Кузнецов Дмитрий Олегович", date(1978, 11, 2), "+7 921 555-01-02", "s2", 7, 10, False, WaitingListStatus.WAITING, "cust2"),
    (3, "Волкова Екатерина Сергеевна", date(1990, 6, 23), "+7 921 555-01-03", "s3", 1, 2, True, WaitingListStatus.SCHEDULED, "cust3"),
    (4, "Морозов Игорь Павлович", date(1965, 1, 30), "+7 921 555-01-04", "s1", 5, 8, False, WaitingListStatus.CONFIRMED, "cust4"),
    (5, "Новикова Ольга Андреевна", date(2001, 9, 14), "+7 921 555-01-05", "s2", 2, 4, False, WaitingListStatus.WAITING, "mgr1"),
    (6, "Лебедев Артем Игоревич", date(1972, 3, 19), "+7 921 555-01-06", "s3", None, None, False, WaitingListStatus.CANCELLED, "cust1"),
    (7, "Соколова Мария Дмитриевна", date(1988, 12, 5), "+7 921 555-01-07", "s1", 10, 14, False, WaitingListStatus.WAITING, "cust3"),
    (8, "Ковалёв Роман Николаевич", date(1995, 7, 8), "+7 921 555-01-08", "s2", 4, 6, True, WaitingListStatus.SCHEDULED, "cust2"),
    (9, "Григорьева Наталья Юрьевна", date(1982, 2, 27), "+7 921 555-01-09", "s3", 6, 9, False, WaitingListStatus.WAITING, "mgr2"),
    (10, "Егоров Владислав Сергеевич", date(1958, 10, 11), "+7 921 555-01-10", "s1", 1, 1, True, WaitingListStatus.CONFIRMED, "cust4"),
]


class Command(BaseCommand):
    help = "Наполнить портал реалистичными русскоязычными демо-данными для ручного тестирования UI."

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help=(
                "Удалить ранее созданные этой командой демо-объекты (по маркеру "
                f"{DEMO_MARKER!r} / префиксам {DEMO_USERNAME_PREFIX!r}, "
                f"{DEMO_INVENTORY_PREFIX!r}, {DEMO_BOARD_SLUG!r}) перед повторным наполнением."
            ),
        )

    def handle(self, *args, **options):
        self._validate_roles()

        if options["flush"]:
            self._flush()

        groups = {role: Group.objects.get_or_create(name=role)[0] for role in ROLE_NAMES}
        catchall, departments = self._ensure_departments()
        users = self._ensure_users(departments, groups)
        board = self._ensure_board(groups)
        devices = self._ensure_devices(departments)
        workorder_count = self._ensure_workorders(departments, devices, users, board)
        waiting_count = self._ensure_waiting_list(users)

        self._report(catchall, departments, users, devices, workorder_count, waiting_count)

    # ------------------------------------------------------------------ guards

    def _validate_roles(self):
        """Не позволяет назначать пользователям роли, которых нет в контракте role_rules."""
        contract = get_contract("role_rules")
        available = {key for key in contract if not key.startswith("$")}
        missing = set(ROLE_NAMES) - available
        if missing:
            raise CommandError(
                "Контракт role_rules не содержит ожидаемые демо-командой роли: "
                + ", ".join(sorted(missing))
            )
        unknown = {spec[4] for spec in USER_SPECS} - available
        if unknown:
            raise CommandError(
                "USER_SPECS ссылается на роли, отсутствующие в role_rules: "
                + ", ".join(sorted(unknown))
            )

    # ------------------------------------------------------------------ flush

    def _flush(self):
        self.stdout.write("Удаление ранее созданных демо-объектов...")

        deleted_waiting = WaitingListEntry.objects.filter(comment__startswith=DEMO_MARKER).delete()[0]
        # Удаление демо-доски каскадно удаляет ее колонки и все заявки на ней
        # (включая их комментарии/вложения/переходы статусов).
        deleted_board = Board.objects.filter(slug=DEMO_BOARD_SLUG).delete()[0]
        deleted_devices = MedicalDevice.objects.filter(inventory_number__startswith=DEMO_INVENTORY_PREFIX).delete()[0]

        # Подразделения с self-FK parent=PROTECT: удаляем от листьев к корню,
        # иначе удаление родителя раньше ребенка упадет с ProtectedError.
        demo_departments = list(Department.objects.filter(name__startswith=DEMO_MARKER))
        demo_departments.sort(key=self._department_depth, reverse=True)
        deleted_departments = 0
        for department in demo_departments:
            department.delete()
            deleted_departments += 1

        deleted_users = User.objects.filter(username__startswith=DEMO_USERNAME_PREFIX).delete()[0]

        self.stdout.write(
            self.style.WARNING(
                "Удалено записей: лист ожидания={}, доска+заявки={}, изделия={}, "
                "подразделения={}, пользователи={}".format(
                    deleted_waiting,
                    deleted_board,
                    deleted_devices,
                    deleted_departments,
                    deleted_users,
                )
            )
        )

    @staticmethod
    def _department_depth(department):
        depth = 0
        node = department.parent
        guard = 0
        while node is not None and guard < 50:
            depth += 1
            node = node.parent
            guard += 1
        return depth

    # ------------------------------------------------------------------ seeding

    def _ensure_departments(self):
        catchall, _ = Department.objects.get_or_create(
            parent=None,
            name=CATCHALL_DEPARTMENT_NAME,
            defaults={},
        )

        departments = {}
        # Два прохода: сначала узлы с родителем=катчолл, затем узлы с
        # родителем из уже созданных узлов (диагностика -> УЗИ/лаборатория).
        for key, short_name, parent_key in DEPARTMENT_SPECS:
            if parent_key is not None:
                continue
            name = f"{DEMO_MARKER} {short_name}"
            department, _ = Department.objects.get_or_create(parent=catchall, name=name)
            departments[key] = department

        for key, short_name, parent_key in DEPARTMENT_SPECS:
            if parent_key is None:
                continue
            name = f"{DEMO_MARKER} {short_name}"
            department, _ = Department.objects.get_or_create(parent=departments[parent_key], name=name)
            departments[key] = department

        return catchall, departments

    def _ensure_users(self, departments, groups):
        users = {}
        for key, suffix, first_name, last_name, role, department_key, is_staff in USER_SPECS:
            username = f"{DEMO_USERNAME_PREFIX}{suffix}"
            user, _ = User.objects.get_or_create(username=username)
            user.first_name = first_name
            user.last_name = last_name
            user.email = f"{username}@{DEMO_EMAIL_DOMAIN}"
            user.is_staff = is_staff
            user.is_active = True
            user.department = departments.get(department_key) if department_key else None
            user.set_password(DEMO_PASSWORD)
            user.save()
            user.groups.set([groups[role]])
            users[key] = user
        return users

    def _ensure_board(self, groups):
        title = f"{DEMO_MARKER} Демо-заявки"
        board, _ = Board.objects.get_or_create(slug=DEMO_BOARD_SLUG, defaults={"title": title})
        if board.title != title:
            board.title = title
            board.save(update_fields=["title"])
        board.allowed_groups.set(groups.values())
        for code, col_title, position, statuses in DEFAULT_COLUMNS:
            board.columns.update_or_create(
                code=code,
                defaults={"title": col_title, "position": position, "statuses": statuses},
            )
        return board

    def _ensure_devices(self, departments):
        devices = {}
        today = date.today()
        for index, spec in enumerate(DEVICE_SPECS, start=1):
            key, name, device_type, manufacturer, country, model, dept_key, status, decommissioned = spec
            inventory_number = f"{DEMO_INVENTORY_PREFIX}{index:04d}"
            defaults = {
                "name": name,
                "device_type": device_type,
                "manufacturer": manufacturer,
                "production_country": country,
                "model": model,
                "serial_number": f"SN-DEMO-{index:04d}",
                "department": departments[dept_key],
                "operational_status": status,
                "commissioned_at": today - timedelta(days=200 + index * 5),
                "service_life_years": 8,
                "notes": f"{DEMO_MARKER} Демонстрационное медицинское изделие для тестового контура портала.",
            }
            if decommissioned:
                defaults["is_archived"] = True
                defaults["archived_at"] = timezone.now() - timedelta(days=10 + index)
                defaults["decommissioned_at"] = today - timedelta(days=10 + index)
                defaults["decommission_reason"] = "Списано по истечении срока службы (демо-данные)."
            else:
                defaults["is_archived"] = False
                defaults["archived_at"] = None
                defaults["decommissioned_at"] = None
                defaults["decommission_reason"] = ""

            device, _ = MedicalDevice.objects.update_or_create(
                inventory_number=inventory_number,
                defaults=defaults,
            )
            devices[key] = device
        return devices

    def _ensure_workorders(self, departments, devices, users, board):
        now = timezone.now()
        count = 0
        for index, dept_key, device_key, author_key, assignee_key, priority, status, days_ago, text in WORKORDER_SPECS:
            title = f"{DEMO_MARKER} Заявка №{index:02d}: {text}"
            description = (
                f"{DEMO_MARKER} Демонстрационная заявка №{index:02d} для тестового контура "
                f"портала. {text}."
            )
            defaults = {
                "board": board,
                "department": departments[dept_key],
                "device": devices.get(device_key) if device_key else None,
                "author": users[author_key],
                "assignee": users.get(assignee_key) if assignee_key else None,
                "priority": priority,
                "status": status,
                "description": description,
            }
            workorder, _ = WorkOrder.objects.update_or_create(title=title, defaults=defaults)

            # created_at/resolved_at/closed_at обновляются напрямую через
            # queryset.update(), чтобы обойти auto_now_add/auto_now и переопределенный
            # save() (иначе даты всегда съезжали бы к моменту запуска команды).
            created_at = now - timedelta(days=days_ago, hours=index % 12)
            timestamp_updates = {"created_at": created_at, "updated_at": created_at}
            if status in (WorkOrderStatus.RESOLVED, WorkOrderStatus.CLOSED):
                resolved_at = created_at + timedelta(days=1)
                timestamp_updates["resolved_at"] = resolved_at
                timestamp_updates["updated_at"] = resolved_at
            else:
                timestamp_updates["resolved_at"] = None
            if status == WorkOrderStatus.CLOSED:
                closed_at = created_at + timedelta(days=2)
                timestamp_updates["closed_at"] = closed_at
                timestamp_updates["updated_at"] = closed_at
            else:
                timestamp_updates["closed_at"] = None
            WorkOrder.objects.filter(pk=workorder.pk).update(**timestamp_updates)
            count += 1
        return count

    def _ensure_waiting_list(self, users):
        today = date.today()
        count = 0
        for index, name, dob, phone, service_id, tag_days, end_days, cito, status, author_key in WAITING_LIST_SPECS:
            comment = f"{DEMO_MARKER} Демонстрационная запись листа ожидания №{index:02d}."
            defaults = {
                "patient_dob": dob,
                "service_id": service_id,
                "date_tag": today + timedelta(days=tag_days) if tag_days is not None else None,
                "date_end": today + timedelta(days=end_days) if end_days is not None else None,
                "priority_cito": cito,
                "comment": comment,
                "status": status,
                "author": users.get(author_key) if author_key else None,
            }
            WaitingListEntry.objects.update_or_create(
                patient_name=name,
                patient_phone=phone,
                defaults=defaults,
            )
            count += 1
        return count

    # ------------------------------------------------------------------ report

    def _report(self, catchall, departments, users, devices, workorder_count, waiting_count):
        self.stdout.write(self.style.SUCCESS("Демо-данные портала наполнены."))
        self.stdout.write(
            f"Подразделения: агрегатор {catchall!s} + {len(departments)} демо-подразделений."
        )
        self.stdout.write(f"Медицинские изделия: {len(devices)}.")
        self.stdout.write(f"Заявки: {workorder_count}.")
        self.stdout.write(f"Записи листа ожидания: {waiting_count}.")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Пароль всех демо-пользователей: {DEMO_PASSWORD}"))
        self.stdout.write("Демо-пользователи (логин — роль — ФИО):")
        for key, suffix, first_name, last_name, role, _dept, _staff in USER_SPECS:
            username = f"{DEMO_USERNAME_PREFIX}{suffix}"
            self.stdout.write(f"  {username} — {role} — {first_name} {last_name}")
