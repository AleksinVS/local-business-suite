from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from apps.core.contract_store import get_contract


class Command(BaseCommand):
    help = "Create initial role groups for Корпоративный портал ВОБ №3."

    def handle(self, *args, **options):
        roles = [role for role in get_contract("role_rules") if not role.startswith("$")]
        for role in roles:
            Group.objects.get_or_create(name=role)
        self.stdout.write(
            self.style.SUCCESS(
                f"Role groups ensured: {', '.join(roles)}"
            )
        )
