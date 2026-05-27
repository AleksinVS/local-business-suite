from django.conf import settings

from apps.workorders.policies import can_manage_departments, can_manage_inventory
from apps.settings_center.policies import can_manage_settings
from apps.memory.policies import can_view_memory_review_queue


def navigation_flags(request):
    user = request.user
    is_authenticated = getattr(user, "is_authenticated", False)
    return {
        "app_display_name": settings.APP_DISPLAY_NAME,
        "show_department_nav": is_authenticated and can_manage_departments(user),
        "show_admin_nav": is_authenticated and (user.is_staff or user.is_superuser),
        "show_ai_nav": is_authenticated,
        "show_ai_admin_nav": is_authenticated and can_manage_inventory(user),
        "show_memory_review_nav": is_authenticated and can_view_memory_review_queue(user),
        "show_settings_center_nav": is_authenticated and can_manage_settings(user),
    }
