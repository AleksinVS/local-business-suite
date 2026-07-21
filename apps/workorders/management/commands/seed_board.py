from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.workorders.models import (
    Board,
    KanbanColumnConfig,
    WorkOrder,
    WorkOrderStatus,
    WorkOrderPriority,
)
from apps.core.models import Department
from django.contrib.auth import get_user_model
import random

User = get_user_model()


class Command(BaseCommand):
    help = "Заполнить доску тестовыми карточками"

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=15,
            help="Количество карточек для создания",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Удалить существующие карточки перед созданием",
        )
        parser.add_argument(
            "--board-slug",
            type=str,
            default=None,
            help="Слаг доски (если не указан - используется первая доска)",
        )

    def handle(self, *args, **options):
        count = options["count"]
        clear = options["clear"]
        board_slug = options["board_slug"]

        board = Board.objects.first()
        if board_slug:
            board = Board.objects.filter(slug=board_slug).first()
            if not board:
                self.stderr.write(f"Доска со слагом '{board_slug}' не найдена")
                return

        if not board:
            self.stderr.write("Доски не найдены")
            return

        if clear:
            deleted = WorkOrder.objects.filter(board=board).delete()[0]
            self.stdout.write(f"Удалено карточек: {deleted}")

        users = list(User.objects.all())
        departments = list(Department.objects.all())

        if not users:
            self.stderr.write("Пользователи не найдены")
            return

        if not departments:
            self.stderr.write("Подразделения не найдены")
            return

        statuses = [
            WorkOrderStatus.NEW,
            WorkOrderStatus.ACCEPTED,
            WorkOrderStatus.IN_PROGRESS,
            WorkOrderStatus.ON_HOLD,
            WorkOrderStatus.RESOLVED,
            WorkOrderStatus.CLOSED,
            WorkOrderStatus.CANCELLED,
        ]

        priorities = [
            WorkOrderPriority.LOW,
            WorkOrderPriority.MEDIUM,
            WorkOrderPriority.HIGH,
            WorkOrderPriority.CRITICAL,
        ]

        titles = [
            "Ремонт рентгеновского аппарата",
            "Замена батареи в дефибрилляторе",
            "Калибровка монитора пациента",
            "Обслуживание вентилятора",
            "Проблема с подключением к сети",
            "Требуется обновление ПО",
            "Проверка системы безопасности",
            "Ремонт подставки для инфузионного насоса",
            "Замена дисплея на УЗИ-сканере",
            "Настройка кардиомонитора",
            "Профилактическое обслуживание",
            "Ошибка при запуске системы",
            "Не работает датчик кислорода",
            "Замена кабеля питания",
            "Обновление документации",
            "Установка дополнительных аксессуаров",
            "Ремонт механизма регулировки",
            "Проверка электрической безопасности",
            "Обновление базы данных устройств",
            "Настройка тревожных сигналов",
        ]

        descriptions = [
            "Требуется срочный ремонт из-за неисправности блока питания",
            "Плановая замена расходных материалов в соответствии с графиком ТО",
            "Необходима калибровка после транспортировки",
            "Проблема возникла после последнего обновления ПО",
            "Пользователь сообщает о периодических сбоях в работе",
            "Требуется проверка и замена изношенных деталей",
            "Нужно выполнить профилактическое обслуживание согласно регламенту",
            "Обнаружена ошибка при самодиагностике системы",
        ]

        existing_count = WorkOrder.objects.filter(board=board).count()
        if existing_count >= count:
            self.stdout.write(
                f"На доске уже {existing_count} карточек, нечего создавать"
            )
            return

        to_create = count - existing_count
        created = 0

        for i in range(to_create):
            title = random.choice(titles) + f" #{existing_count + i + 1}"
            description = random.choice(descriptions)
            status = random.choice(statuses)
            priority = random.choice(priorities)
            author = random.choice(users)
            assignee = random.choice(users) if random.random() > 0.3 else None

            resolved_at = None
            closed_at = None

            if status == WorkOrderStatus.RESOLVED:
                resolved_at = timezone.now()
            elif status == WorkOrderStatus.CLOSED:
                resolved_at = timezone.now()
                closed_at = timezone.now()

            workorder = WorkOrder.objects.create(
                board=board,
                title=title,
                description=description,
                department=random.choice(departments),
                priority=priority,
                status=status,
                author=author,
                assignee=assignee,
                resolved_at=resolved_at,
                closed_at=closed_at,
            )

            created += 1
            if created % 5 == 0:
                self.stdout.write(f"Создано: {created}/{to_create}")

        total = WorkOrder.objects.filter(board=board).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Успешно создано {created} карточек. Всего на доске: {total}"
            )
        )

        stats = {}
        for status, label in WorkOrderStatus.choices:
            stats[label] = WorkOrder.objects.filter(
                board=board, status=status
            ).count()

        self.stdout.write("\nРаспределение по статусам:")
        for label, count in stats.items():
            self.stdout.write(f"  {label}: {count}")