from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.test import Client, override_settings
from django.urls import reverse

from apps.core.models import Department

from ...models import Board, KanbanColumnConfig, WorkOrder
from ...policies import ROLE_CUSTOMER, default_board_access_applies, user_roles
from ...selectors import visible_boards_queryset


class Command(BaseCommand):
    help = "Проверяет базовый read-only доступ к канбану без сохранения тестовых данных."

    def handle(self, *args, **options):
        User = get_user_model()
        prefix = "__default_board_access_e2e_"
        if User.objects.filter(username__startswith=prefix).exists():
            raise CommandError("Тестовые логины уже заняты; существующие данные не изменены.")

        with transaction.atomic():
            department = Department.objects.create(name=f"{prefix}department")
            customer_group, _ = Group.objects.get_or_create(name=ROLE_CUSTOMER)
            board = Board.objects.create(
                title="E2E базовая доска",
                slug="default-board-access-e2e",
            )
            board.allowed_groups.add(customer_group)
            if not board.allowed_groups.filter(pk=customer_group.pk).exists():
                raise CommandError(
                    "Не удалось привязать временную доску к группе customer: "
                    f"board_id={board.pk}, group_id={customer_group.pk}."
                )
            KanbanColumnConfig.objects.create(
                board=board,
                code="new",
                title="Новые",
                position=10,
                statuses=["new"],
            )
            author = User.objects.create_user(
                username=f"{prefix}author",
                department=department,
            )
            author.groups.add(customer_group)
            viewer = User.objects.create_user(
                username=f"{prefix}viewer",
                department=department,
            )
            workorder = WorkOrder.objects.create(
                board=board,
                author=author,
                department=department,
                title="E2E заявка для просмотра",
                description="Проверка базового доступа только на чтение.",
            )

            # Django Client использует служебный host `testserver`, которого нет
            # в production ALLOWED_HOSTS. Разрешаем его только внутри команды:
            # реальные настройки host приложения при этом не меняются.
            with override_settings(ALLOWED_HOSTS=["testserver"]):
                client = Client()
                client.force_login(viewer)
                if not visible_boards_queryset(viewer).filter(pk=board.pk).exists():
                    raise CommandError(
                        "Базовый профиль не включил временную доску в доступный набор: "
                        f"applies={default_board_access_applies(viewer)}, "
                        f"active={viewer.is_active}, roles={sorted(user_roles(viewer))}, "
                        "board_groups="
                        f"{list(board.allowed_groups.values_list('name', flat=True))}."
                    )
                response = client.get(
                    reverse("workorders:board_specific", kwargs={"board_slug": board.slug})
                )
                body = response.content.decode("utf-8")
                if response.status_code != 200 or workorder.title not in body:
                    request_user = getattr(
                        getattr(response, "wsgi_request", None), "user", None
                    )
                    raise CommandError(
                        "Пользователь без роли не увидел разрешенную заявку: "
                        f"HTTP {response.status_code}, request_user="
                        f"{getattr(request_user, 'username', '<нет>')!r}, "
                        f"authenticated={getattr(request_user, 'is_authenticated', False)}."
                    )
                if "Создать заявку" in body:
                    raise CommandError("Пользователю без роли показано действие создания.")
                if client.get(reverse("workorders:create")).status_code != 403:
                    raise CommandError(
                        "Сервер не запретил создание заявки пользователю без роли."
                    )

            transaction.set_rollback(True)

        self.stdout.write(
            self.style.SUCCESS("default_board_access_e2e: OK (тестовые данные откатились)")
        )
