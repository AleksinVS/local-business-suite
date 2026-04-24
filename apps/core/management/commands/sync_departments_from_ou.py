from django.core.management.base import BaseCommand
from django.db import transaction
from apps.core.models import Department, OrganizationalUnit


class Command(BaseCommand):
    help = "Заполнить подразделения на основе оргструктуры (до 3 уровня включительно)"

    def handle(self, *args, **options):
        self.stdout.write("Начинаю заполнение подразделений на основе OU...")

        # Получаем OU уровня 2 и 3 (подразделения и отделы)
        level_2_ous = OrganizationalUnit.objects.filter(level=2).order_by("name")
        level_3_ous = OrganizationalUnit.objects.filter(level=3).order_by("name")

        total_to_create = level_2_ous.count() + level_3_ous.count()
        created_count = 0
        updated_count = 0

        with transaction.atomic():
            # Сначала создаем подразделения уровня 2
            self.stdout.write(
                f"Обработка {level_2_ous.count()} подразделений уровня 2..."
            )

            for ou in level_2_ous:
                dept, created = Department.objects.update_or_create(
                    name=ou.name,
                    defaults={
                        "parent": None,  # Подразделения уровня 2 не имеют родителя
                    },
                )

                if created:
                    created_count += 1
                    self.stdout.write(f"  ✅ Создано: {ou.name}")
                else:
                    updated_count += 1
                    self.stdout.write(f"  🔄 Обновлено: {ou.name}")

            # Затем создаем отделы уровня 3
            self.stdout.write(f"\nОбработка {level_3_ous.count()} отделов уровня 3...")

            for ou in level_3_ous:
                # Находим родительское подразделение (уровень 2)
                parent_ou = ou.parent
                parent_dept = None

                if parent_ou and parent_ou.level == 2:
                    # Ищем соответствующее подразделение
                    parent_dept = Department.objects.filter(
                        name=parent_ou.name, parent__isnull=True
                    ).first()

                dept, created = Department.objects.update_or_create(
                    name=ou.name,
                    defaults={
                        "parent": parent_dept,
                    },
                )

                if created:
                    created_count += 1
                    self.stdout.write(
                        f"  ✅ Создано: {ou.name} (родитель: {parent_dept.name if parent_dept else 'Нет'})"
                    )
                else:
                    updated_count += 1
                    self.stdout.write(f"  🔄 Обновлено: {ou.name}")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nУспешно завершено: "
                f"{created_count} создано, {updated_count} обновлено"
            )
        )

        # Выводим статистику
        self.stdout.write("\nСтатистика подразделений:")
        self.stdout.write(f"Всего подразделений: {Department.objects.count()}")

        root_depts = Department.objects.filter(parent__isnull=True)
        self.stdout.write(f"Корневых подразделений: {root_depts.count()}")

        for dept in root_depts[:5]:
            children_count = dept.children.count()
            self.stdout.write(f"  {dept.name}: {children_count} отделов")
