from django.contrib.auth.models import AbstractUser, Group, Permission
from django.db import models


class User(AbstractUser):
    """
    Расширенная модель пользователя с привязкой к организационной структуре.
    """

    department = models.ForeignKey(
        "core.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
        verbose_name="Подразделение",
        help_text="Подразделение пользователя (синхронизируется с AD OU)",
    )

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    def __str__(self):
        return self.get_full_name() or self.username

    def get_department_path(self):
        """Получить полный путь подразделения"""
        if self.department:
            return self.department.full_name
        return "Без подразделения"

    def get_ou_path(self):
        """Получить полный путь OU"""
        if self.organizational_unit:
            return self.organizational_unit.get_path()
        return "Без OU"
