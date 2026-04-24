from django.db import models
from django.core.cache import cache


class OrganizationalUnit(models.Model):
    """
    Модель для хранения организационной структуры из Active Directory.
    Хранит иерархию OU для организации структуры компании.
    """

    name = models.CharField(max_length=255, db_index=True)
    distinguished_name = models.CharField(max_length=1024, unique=True, db_index=True)
    description = models.TextField(blank=True, null=True)
    level = models.PositiveSmallIntegerField(help_text="Уровень вложенности (2-5)")
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        help_text="Родительская OU",
    )
    dn_level_1 = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
        help_text="Организация (уровень 1)",
    )
    dn_level_2 = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
        help_text="Подразделение (уровень 2)",
    )
    dn_level_3 = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
        help_text="Отдел (уровень 3)",
    )
    dn_level_4 = models.CharField(
        max_length=255, blank=True, null=True, help_text="Подотдел (уровень 4)"
    )
    dn_level_5 = models.CharField(
        max_length=255, blank=True, null=True, help_text="Группа (уровень 5)"
    )

    # Метаданные для синхронизации
    last_synced_at = models.DateTimeField(auto_now=True)
    ad_last_modified = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Организационная единица"
        verbose_name_plural = "Организационные единицы"
        ordering = ["level", "name"]
        indexes = [
            models.Index(fields=["level"]),
            models.Index(fields=["dn_level_1"]),
            models.Index(fields=["dn_level_2"]),
            models.Index(fields=["parent"]),
        ]

    def __str__(self):
        return self.name

    def get_path(self):
        """Получить полный путь OU от корня"""
        parts = []
        current = self
        while current:
            parts.append(current.name)
            current = current.parent
        return " / ".join(reversed(parts))

    def get_full_dn(self):
        """Получить полный distinguished name"""
        return self.distinguished_name

    def get_children(self):
        """Получить дочерние OU"""
        return self.children.filter(is_active=True).order_by("name")

    @classmethod
    def get_root_ous(cls):
        """Получить корневые OU (без родителя)"""
        return cls.objects.filter(parent__isnull=True, is_active=True).order_by("name")

    @classmethod
    def get_by_dn(cls, dn):
        """Получить OU по distinguished name"""
        return cls.objects.filter(distinguished_name=dn, is_active=True).first()

    def get_ancestors(self):
        """Получить всех предков OU"""
        ancestors = []
        current = self.parent
        while current:
            ancestors.append(current)
            current = current.parent
        return ancestors

    def get_level_name(self, level):
        """Получить название уровня"""
        level_mapping = {
            1: "Организация",
            2: "Подразделение",
            3: "Отдел",
            4: "Подотдел",
            5: "Группа",
        }
        return level_mapping.get(level, f"Уровень {level}")
