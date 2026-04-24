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
    organizational_unit = models.ForeignKey(
        "core.OrganizationalUnit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
        verbose_name="Организационная единица",
        help_text="Полный путь OU в Active Directory",
    )
    # Для избежания конфликтов со стандартной моделью User
    groups = models.ManyToManyField(
        Group,
        verbose_name="Группы",
        blank=True,
        help_text="Группы, к которым принадлежит пользователь",
        related_name="custom_user_set",
        related_query_name="custom_user",
    )
    user_permissions = models.ManyToManyField(
        Permission,
        verbose_name="Пользовательские права",
        blank=True,
        help_text="Специальные права для этого пользователя",
        related_name="custom_user_set",
        related_query_name="custom_user",
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
