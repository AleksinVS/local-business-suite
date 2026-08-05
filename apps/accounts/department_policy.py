from __future__ import annotations


ORGANIZATION_ROOT_DEPARTMENT_NAME = "Вологодская областная больница №3"
UNASSIGNED_USER_DEPARTMENT_NAME = "Не назначено — требуется уточнение"


def get_unassigned_user_department():
    """Возвращает безопасное подразделение для программно созданной учётной записи."""

    from apps.core.models import Department

    root, _created = Department.objects.get_or_create(
        parent=None,
        name=ORGANIZATION_ROOT_DEPARTMENT_NAME,
    )
    department, _created = Department.objects.get_or_create(
        parent=root,
        name=UNASSIGNED_USER_DEPARTMENT_NAME,
    )
    return department


def available_user_departments():
    """Реальные подразделения, которые разрешено выбрать администратору."""

    from apps.core.models import Department

    return Department.objects.exclude(
        name=UNASSIGNED_USER_DEPARTMENT_NAME,
        parent__name=ORGANIZATION_ROOT_DEPARTMENT_NAME,
        parent__parent__isnull=True,
    ).order_by("parent_id", "name", "id")


def is_unassigned_user_department(department) -> bool:
    if department is None:
        return True
    return bool(
        department.name == UNASSIGNED_USER_DEPARTMENT_NAME
        and department.parent_id
        and department.parent is not None
        and department.parent.name == ORGANIZATION_ROOT_DEPARTMENT_NAME
        and department.parent.parent_id is None
    )
