from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from apps.accounts.ldap_backend import find_ad_user, sync_user_from_ad, LDAPConfig

User = get_user_model()


class Command(BaseCommand):
    help = "Найти пользователя в AD и создать его локально"

    def add_arguments(self, parser):
        parser.add_argument("username", type=str, help="Логин пользователя в AD (например, volodin.yi)")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Только показать информацию без создания пользователя",
        )

    def handle(self, *args, **options):
        username = options["username"]
        dry_run = options["dry_run"]

        try:
            config = LDAPConfig.from_env()
        except Exception as exc:
            raise CommandError(f"LDAP конфигурация недоступна: {exc}")

        self.stdout.write(f"Поиск пользователя '{username}' в AD...")

        try:
            user_dn, attributes = find_ad_user(config, username)
        except Exception as exc:
            raise CommandError(f"Ошибка поиска в AD: {exc}")

        if not user_dn:
            self.stdout.write(
                self.style.WARNING(f"Пользователь '{username}' не найден в AD")
            )
            return

        self.stdout.write(self.style.SUCCESS(f"Найден пользователь в AD:"))
        self.stdout.write(f"  DN: {user_dn}")
        self.stdout.write(f"  sAMAccountName: {attributes.get('sAMAccountName')}")
        self.stdout.write(f"  displayName: {attributes.get('displayName')}")
        self.stdout.write(f"  givenName: {attributes.get('givenName')}")
        self.stdout.write(f"  sn: {attributes.get('sn')}")
        self.stdout.write(f"  mail: {attributes.get('mail')}")
        self.stdout.write(f"  userPrincipalName: {attributes.get('userPrincipalName')}")
        self.stdout.write(
            f"  memberOf: {len(attributes.get('memberOf', []))} групп"
        )

        sam_account = attributes.get("sAMAccountName", username)
        existing_user = User.objects.filter(username__iexact=sam_account).first()

        if existing_user:
            self.stdout.write(
                self.style.WARNING(
                    f"Пользователь '{sam_account}' уже существует локально (ID: {existing_user.pk})"
                )
            )
            if not dry_run:
                sync_user_from_ad(existing_user, attributes, config.group_role_map)
                self.stdout.write(
                    self.style.SUCCESS("Пользователь синхронизирован с AD")
                )
            return

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run: пользователь не создан"))
            return

        self.stdout.write(f"Создание локального пользователя '{sam_account}'...")

        user = User.objects.create(
            username=sam_account,
            is_active=True,
            email=attributes.get("mail", ""),
            first_name=attributes.get("givenName", ""),
            last_name=attributes.get("sn", ""),
        )

        sync_user_from_ad(user, attributes, config.group_role_map)

        self.stdout.write(
            self.style.SUCCESS(
                f"Пользователь создан успешно:\n"
                f"  ID: {user.pk}\n"
                f"  Username: {user.username}\n"
                f"  Email: {user.email}\n"
                f"  Имя: {user.get_full_name()}\n"
                f"  Активен: {user.is_active}\n"
                f"  Группы: {', '.join([g.name for g in user.groups.all()]) or 'нет'}"
            )
        )