from django.conf import settings

from apps.workorders.policies import (
    can_access_inventory,
    can_access_workorders,
    can_manage_departments,
    can_manage_inventory,
    can_manage_roles,
    can_view_analytics,
    has_product_role_access,
)
from apps.accounts.access_contracts import can_edit_role_definitions
from apps.ai.skill_authoring import can_manage_ai_skills
from apps.settings_center.policies import can_manage_settings
from apps.memory.policies import can_view_memory_review_queue
from apps.waiting_list.policies import can_view_waiting_list


def navigation_flags(request):
    user = request.user
    is_authenticated = getattr(user, "is_authenticated", False)
    flags = {
        "app_display_name": settings.APP_DISPLAY_NAME,
        "show_workorders_nav": is_authenticated and can_access_workorders(user),
        "show_inventory_nav": is_authenticated and can_access_inventory(user),
        "show_department_nav": is_authenticated and can_manage_departments(user),
        "show_access_nav": is_authenticated and (
            can_manage_roles(user) or can_edit_role_definitions(user)
        ),
        "show_admin_nav": is_authenticated and (user.is_staff or user.is_superuser),
        "show_ai_nav": is_authenticated and has_product_role_access(user),
        "show_ai_admin_nav": is_authenticated and can_manage_ai_skills(user),
        "show_memory_review_nav": is_authenticated and can_view_memory_review_queue(user),
        "show_settings_center_nav": is_authenticated and can_manage_settings(user),
        "show_analytics_nav": is_authenticated and can_view_analytics(user),
        "show_waiting_list_nav": is_authenticated and can_view_waiting_list(user),
    }
    navigation_ids = (
        ("board", "show_workorders_nav"),
        ("inventory", "show_inventory_nav"),
        ("departments", "show_department_nav"),
        ("user-access", "show_access_nav"),
        ("chat", "show_ai_nav"),
        ("ai-hub", "show_ai_admin_nav"),
        ("settings-center", "show_settings_center_nav"),
        ("memory-review", "show_memory_review_nav"),
        ("admin", "show_admin_nav"),
        ("analytics", "show_analytics_nav"),
        ("waiting-list", "show_waiting_list_nav"),
    )
    flags["allowed_navigation_ids"] = [
        item_id for item_id, flag_name in navigation_ids if flags[flag_name]
    ]
    return flags
