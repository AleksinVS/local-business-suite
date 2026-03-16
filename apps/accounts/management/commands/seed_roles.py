from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from apps.workorders.policies import ROLE_CUSTOMER, ROLE_MANAGER, ROLE_TECHNICIAN


class Command(BaseCommand):
    help = "Create initial role groups for Local Business Suite."

    def handle(self, *args, **options):
        for role in (ROLE_CUSTOMER, ROLE_TECHNICIAN, ROLE_MANAGER):
            Group.objects.get_or_create(name=role)
        self.stdout.write(self.style.SUCCESS("Role groups ensured: customer, technician, manager"))
