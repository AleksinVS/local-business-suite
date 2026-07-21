def can_manage_settings(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
    )


def can_manage_users(user) -> bool:
    return bool(getattr(user, "is_authenticated", False) and getattr(user, "is_superuser", False))


def can_manage_privileged_flags(user) -> bool:
    return bool(getattr(user, "is_authenticated", False) and getattr(user, "is_superuser", False))
