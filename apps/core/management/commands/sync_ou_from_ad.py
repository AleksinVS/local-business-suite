from django.core.management.base import BaseCommand
from django.db import transaction
from apps.core.models_ou import OrganizationalUnit
from apps.accounts.ldap_backend import LDAPConfig, service_connection, _ldap
import re


class Command(BaseCommand):
    help = "Синхронизировать организационные единицы из Active Directory"

    def handle(self, *args, **options):
        self.stdout.write("Начинаю синхронизацию OU из AD...")

        config = LDAPConfig.from_env()
        ou_filter = "(objectClass=organizationalUnit)"
        ou_attributes = ["name", "distinguishedName", "description", "objectCategory"]

        try:
            with service_connection(config) as conn:
                conn.search(
                    config.search_base,
                    ou_filter,
                    search_scope=_ldap().SUBTREE,
                    attributes=ou_attributes,
                )

                if not conn.entries:
                    self.stdout.write(self.style.WARNING("OU не найдены в AD"))
                    return

                ous = conn.entries
                self.stdout.write(f"Найдено {len(ous)} организационных единиц")

                # Создаем маппинг DN -> уровень и компоненты
                ou_data = {}
                for ou in ous:
                    dn = str(ou.entry_dn)
                    name = getattr(ou, "name", "")
                    description = getattr(ou, "description", "")

                    # Извлекаем уровень и компоненты DN
                    path_parts = dn.split(",")
                    level = len(path_parts) - 1  # Вычитаем DC=MSCHER,DC=local

                    # Извлекаем компоненты уровня
                    dn_levels = self._parse_dn_components(dn)

                    ou_data[dn] = {
                        "name": name,
                        "distinguished_name": dn,
                        "description": description,
                        "level": level,
                        "dn_levels": dn_levels,
                    }

                # Определяем родительские связи
                for dn, data in ou_data.items():
                    parent_dn = self._get_parent_dn(dn)
                    if parent_dn in ou_data:
                        data["parent_dn"] = parent_dn

                # Сохраняем в базу
                with transaction.atomic():
                    created_count = 0
                    updated_count = 0

                    for dn, data in ou_data.items():
                        parent = None
                        if "parent_dn" in data:
                            parent = OrganizationalUnit.objects.filter(
                                distinguished_name=data["parent_dn"]
                            ).first()

                        obj, created = OrganizationalUnit.objects.update_or_create(
                            distinguished_name=dn,
                            defaults={
                                "name": data["name"],
                                "description": data["description"],
                                "level": data["level"],
                                "parent": parent,
                                "dn_level_1": data["dn_levels"].get(1),
                                "dn_level_2": data["dn_levels"].get(2),
                                "dn_level_3": data["dn_levels"].get(3),
                                "dn_level_4": data["dn_levels"].get(4),
                                "dn_level_5": data["dn_levels"].get(5),
                            },
                        )

                        if created:
                            created_count += 1
                        else:
                            updated_count += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Успешно синхронизировано: "
                        f"{created_count} создано, {updated_count} обновлено"
                    )
                )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Ошибка при синхронизации: {e}"))
            raise

    def _parse_dn_components(self, dn):
        """Извлекает компоненты DN по уровням"""
        components = dn.split(",")
        levels = {}

        for component in reversed(components):
            if component.startswith("OU="):
                parts = component.split("=", 1)
                if len(parts) == 2:
                    name = parts[1]
                    level = len(components) - components.index(component) - 1
                    if 1 <= level <= 5:
                        levels[level] = name
            elif component.startswith("DC="):
                parts = component.split("=", 1)
                if len(parts) == 2:
                    # DC components - уровень 1
                    if 1 not in levels:
                        levels[1] = parts[1]

        return levels

    def _get_parent_dn(self, dn):
        """Получает distinguished name родительской OU"""
        parts = dn.split(",")
        if len(parts) > 2:  # Есть родитель (минимум OU=, DC=, DC=)
            return ",".join(parts[1:])
        return None
