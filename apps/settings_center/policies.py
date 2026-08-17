from django.contrib.auth import get_user_model


def can_manage_settings(user) -> bool:
    """Return product Settings Center authority from a fresh actor snapshot.

    ``is_staff`` is deliberately not consulted: it grants Django Admin access
    only.  Product administration is a role capability and superuser remains
    the break-glass path.
    """
    if not getattr(user, "is_authenticated", False) or not getattr(user, "pk", None):
        return False
    current = get_user_model().objects.filter(pk=user.pk, is_active=True).first()
    if not current:
        return False
    if current.is_superuser:
        return True
    from apps.workorders.policies import has_role_capability

    return bool(has_role_capability(current, "manage_settings"))


def can_manage_users(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and getattr(user, "is_superuser", False)
    )


def can_manage_privileged_flags(user) -> bool:
    return can_manage_users(user)
