from apps.workorders.policies import can_manage_inventory


def navigation_flags(request):
    user = request.user
    is_authenticated = getattr(user, "is_authenticated", False)
    return {
        "show_department_nav": is_authenticated and can_manage_inventory(user),
        "show_admin_nav": is_authenticated and (user.is_staff or user.is_superuser),
    }
