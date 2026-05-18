from django.contrib.auth.models import Group
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create initial role groups for Корпоративный портал ВОБ №3."

    def handle(self, *args, **options):
        roles = [role for role in settings.LOCAL_BUSINESS_ROLE_RULES if not role.startswith("$")]
        for role in roles:
            Group.objects.get_or_create(name=role)
        self.stdout.write(
            self.style.SUCCESS(
                f"Role groups ensured: {', '.join(roles)}"
            )
        )
