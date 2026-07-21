from datetime import date, timedelta

from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models import Department
from apps.inventory.models import MedicalDevice, OperationalStatus
from apps.workorders.models import Board, WorkOrder, WorkOrderPriority, WorkOrderStatus

User = get_user_model()

DEMO_PASSWORD = "HospitalDemo-2026!"
DEMO_EMAIL_DOMAIN = "demo.local"
DEMO_MARKER = "[hospital-demo]"
DEFAULT_COLUMNS = [
    ("new", "Новые", 10, ["new"]),
    ("in_progress", "В работе", 20, ["accepted", "in_progress", "on_hold"]),
    ("done", "Выполнены", 30, ["resolved"]),
    ("archive", "Архив", 40, ["closed", "cancelled"]),
]


class Command(BaseCommand):
    help = "Seed demo hospital data: departments, users, devices, and work orders."

    def handle(self, *args, **options):
        groups = {name: Group.objects.get_or_create(name=name)[0] for name in ("manager", "technician", "customer")}

        main_board, _ = Board.objects.get_or_create(
            slug="main",
            defaults={"title": "Основная доска"},
        )
        main_board.allowed_groups.set(groups.values())
        backlog_board, _ = Board.objects.get_or_create(
            slug="backlog",
            defaults={"title": "Техподдержка"},
        )
        backlog_board.title = "Техподдержка"
        backlog_board.save(update_fields=["title"])
        backlog_board.allowed_groups.set(groups.values())

        for board in (main_board, backlog_board):
            for code, title, position, statuses in DEFAULT_COLUMNS:
                board.columns.update_or_create(
                    code=code,
                    defaults={
                        "title": title,
                        "position": position,
                        "statuses": statuses,
                    },
                )

        departments = {}

        def ensure_department(name, parent=None):
            department, _ = Department.objects.get_or_create(
                name=name,
                parent=parent,
            )
            departments[name] = department
            return department

        stationary = ensure_department("Стационар")
        polyclinic = ensure_department("Поликлиника")
        administration = ensure_department("Администрация")
        diagnostics = ensure_department("Диагностика", parent=polyclinic)
        ensure_department("Реанимация", parent=stationary)
        ensure_department("ОЛД1", parent=diagnostics)
        ensure_department("ОЛД2", parent=diagnostics)
        ensure_department("УЗИ", parent=diagnostics)

        users = {}
        user_specs = [
            ("chief_manager", "manager", "Главный", "Менеджер", True, administration),
            ("tech_ivanov", "technician", "Иван", "Иванов", False, stationary),
            ("tech_petrov", "technician", "Петр", "Петров", False, diagnostics),
            ("nurse_stationary", "customer", "Анна", "Соколова", False, stationary),
            ("registry_operator", "customer", "Мария", "Орлова", False, diagnostics),
            ("admin_office", "customer", "Ольга", "Киреева", False, administration),
        ]
        for username, role, first_name, last_name, is_staff, department in user_specs:
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@{DEMO_EMAIL_DOMAIN}",
                    "first_name": first_name,
                    "last_name": last_name,
                    "is_staff": is_staff,
                },
            )
            user.email = f"{username}@{DEMO_EMAIL_DOMAIN}"
            user.first_name = first_name
            user.last_name = last_name
            user.is_staff = is_staff
            user.department = department
            user.set_password(DEMO_PASSWORD)
            user.save()
            user.groups.set([groups[role]])
            users[username] = user

        device_specs = [
            ("КТ аппарат Siemens SOMATOM", "KT-0001", "KT-2026-01", departments["ОЛД1"], "Кабинет КТ", OperationalStatus.ACTIVE),
            ("КТ аппарат GE Optima", "KT-0002", "KT-2026-02", departments["ОЛД2"], "Кабинет КТ", OperationalStatus.MAINTENANCE),
            ("УЗИ аппарат Mindray DC-80", "US-0001", "US-2026-01", departments["УЗИ"], "Кабинет УЗИ", OperationalStatus.ACTIVE),
            ("Монитор пациента Phillips", "MON-0001", "MON-2026-01", departments["Стационар"], "Пост медсестры", OperationalStatus.ACTIVE),
            ("Аппарат ИВЛ Hamilton", "IVL-0001", "IVL-2026-01", departments["Стационар"], "Реанимация", OperationalStatus.ACTIVE),
            ("Сервер регистратуры", "ADM-0001", "ADM-2026-01", departments["Администрация"], "Серверная", OperationalStatus.RESERVED),
        ]
        devices = {}
        for name, serial_number, inventory_number, department, location, status in device_specs:
            device, _ = MedicalDevice.objects.get_or_create(
                serial_number=serial_number,
                defaults={
                    "name": name,
                    "inventory_number": inventory_number,
                    "department": department,
                    "location": location,
                    "operational_status": status,
                    "commissioned_at": date.today() - timedelta(days=200),
                },
            )
            device.name = name
            device.inventory_number = inventory_number
            device.department = department
            device.location = location
            device.operational_status = status
            device.commissioned_at = date.today() - timedelta(days=200)
            device.save()
            devices[serial_number] = device

        workorders = [
            ("Починить раковину в процедурном кабинете", departments["Поликлиника"], None, "nurse_stationary", None, WorkOrderPriority.MEDIUM, WorkOrderStatus.NEW),
            ("Заменить светильник в коридоре стационара", departments["Стационар"], None, "nurse_stationary", "tech_ivanov", WorkOrderPriority.MEDIUM, WorkOrderStatus.ACCEPTED),
            ("КТ аппарат не включается", departments["ОЛД1"], "KT-0001", "registry_operator", "tech_petrov", WorkOrderPriority.CRITICAL, WorkOrderStatus.IN_PROGRESS),
            ("КТ аппарат выдает ошибку охлаждения", departments["ОЛД2"], "KT-0002", "registry_operator", "tech_ivanov", WorkOrderPriority.HIGH, WorkOrderStatus.ON_HOLD),
            ("УЗИ аппарат требует калибровки", departments["УЗИ"], "US-0001", "nurse_stationary", "tech_ivanov", WorkOrderPriority.HIGH, WorkOrderStatus.RESOLVED),
            ("Монитор пациента не печатает кривую", departments["Стационар"], "MON-0001", "nurse_stationary", "tech_petrov", WorkOrderPriority.HIGH, WorkOrderStatus.CLOSED),
            ("Аппарат ИВЛ показывает низкое давление", departments["Стационар"], "IVL-0001", "nurse_stationary", "tech_ivanov", WorkOrderPriority.CRITICAL, WorkOrderStatus.CANCELLED),
            ("Протечка смесителя в ординаторской", departments["Стационар"], None, "admin_office", None, WorkOrderPriority.LOW, WorkOrderStatus.NEW),
            ("Не работает розетка в кабинете УЗИ", departments["УЗИ"], None, "registry_operator", "tech_petrov", WorkOrderPriority.MEDIUM, WorkOrderStatus.ACCEPTED),
            ("Светильник в холле мигает", departments["Администрация"], None, "admin_office", "tech_ivanov", WorkOrderPriority.LOW, WorkOrderStatus.IN_PROGRESS),
            ("Сервер регистратуры перегревается", departments["Администрация"], "ADM-0001", "admin_office", "tech_petrov", WorkOrderPriority.HIGH, WorkOrderStatus.ON_HOLD),
            ("КТ аппарат требует замены UPS", departments["ОЛД1"], "KT-0001", "chief_manager", "tech_ivanov", WorkOrderPriority.HIGH, WorkOrderStatus.RESOLVED),
            ("УЗИ аппарат не сохраняет снимки", departments["УЗИ"], "US-0001", "registry_operator", "tech_petrov", WorkOrderPriority.HIGH, WorkOrderStatus.CLOSED),
            ("Починить дверь в архив", departments["Администрация"], None, "admin_office", None, WorkOrderPriority.LOW, WorkOrderStatus.CANCELLED),
            ("Монитор пациента потерял сеть", departments["Стационар"], "MON-0001", "nurse_stationary", "tech_ivanov", WorkOrderPriority.MEDIUM, WorkOrderStatus.NEW),
            ("Заменить лампу в приемном покое", departments["Стационар"], None, "nurse_stationary", "tech_petrov", WorkOrderPriority.LOW, WorkOrderStatus.ACCEPTED),
            ("КТ аппарат шумит при запуске", departments["ОЛД2"], "KT-0002", "registry_operator", "tech_ivanov", WorkOrderPriority.HIGH, WorkOrderStatus.IN_PROGRESS),
            ("Починить раковину в санузле администрации", departments["Администрация"], None, "admin_office", "tech_petrov", WorkOrderPriority.MEDIUM, WorkOrderStatus.ON_HOLD),
            ("УЗИ аппарат не печатает отчет", departments["УЗИ"], "US-0001", "registry_operator", "tech_ivanov", WorkOrderPriority.MEDIUM, WorkOrderStatus.RESOLVED),
            ("Светильник в коридоре поликлиники перегорел", departments["Поликлиника"], None, "registry_operator", "tech_petrov", WorkOrderPriority.LOW, WorkOrderStatus.CLOSED),
        ]

        for index, (title, department, device_serial, author_key, assignee_key, priority, status) in enumerate(workorders, start=1):
            description = f"{DEMO_MARKER} Демонстрационная заявка №{index} для тестового контура больницы."
            defaults = {
                "board": main_board,
                "department": department,
                "device": devices.get(device_serial) if device_serial else None,
                "author": users[author_key],
                "assignee": users.get(assignee_key) if assignee_key else None,
                "priority": priority,
                "status": status,
            }
            if status == WorkOrderStatus.RESOLVED:
                defaults["resolved_at"] = timezone.now()
            if status == WorkOrderStatus.CLOSED:
                defaults["resolved_at"] = timezone.now()
                defaults["closed_at"] = timezone.now()
            workorder, _ = WorkOrder.objects.get_or_create(
                title=title,
                description=description,
                defaults=defaults,
            )
            workorder.board = main_board
            workorder.department = department
            workorder.device = devices.get(device_serial) if device_serial else None
            workorder.author = users[author_key]
            workorder.assignee = users.get(assignee_key) if assignee_key else None
            workorder.priority = priority
            workorder.status = status
            workorder.description = description
            workorder.save()

        self.stdout.write(self.style.SUCCESS("Demo hospital data ensured."))
        self.stdout.write(self.style.SUCCESS(f"Demo user password: {DEMO_PASSWORD}"))
