from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import GroupProfile
from apps.core.contract_store import get_contract
from apps.memory.policies import MEMORY_REVIEW_GROUP_PROFILES


class Command(BaseCommand):
    help = (
        "Create predefined access groups (contract roles + memory groups) "
        "and sync their human-readable profiles."
    )

    def handle(self, *args, **options):
        seeded = []

        role_rules = get_contract("role_rules")
        for role, config in role_rules.items():
            if role.startswith("$") or not isinstance(config, dict):
                continue
            self._ensure_contract_role(
                name=role,
                title=config.get("display_name", ""),
                description=config.get("description", ""),
            )
            seeded.append(role)

        for name, (title, description) in MEMORY_REVIEW_GROUP_PROFILES.items():
            self._ensure_group(name=name, title=title, description=description)
            seeded.append(name)

        self.stdout.write(
            self.style.SUCCESS(f"Predefined groups ensured: {', '.join(seeded)}")
        )

    def _ensure_group(self, *, name, title, description):
        group, _ = Group.objects.get_or_create(name=name)
        GroupProfile.objects.update_or_create(
            group=group,
            defaults={
                "title": title,
                "description": description,
                "is_predefined": True,
            },
        )

    def _ensure_contract_role(self, *, name, title, description):
        """Trusted repair for a role already authoritative in role_rules."""

        group, _created = Group.objects.get_or_create(name=name)
        profile = GroupProfile.objects.filter(group=group).first()
        if profile is not None and not profile.is_predefined:
            raise CommandError(
                f"Contract role group '{name}' has a non-predefined technical profile."
            )
        GroupProfile.objects.update_or_create(
            group=group,
            defaults={
                "title": title,
                "description": description,
                "is_predefined": True,
            },
        )
