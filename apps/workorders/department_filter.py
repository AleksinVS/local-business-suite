from dataclasses import dataclass


@dataclass(frozen=True)
class DepartmentFilterSelection:
    """Нормализованный фильтр поверх уже разрешенных подразделений."""

    visible_departments: tuple
    selected_ids: tuple[int, ...]
    branch_ids: frozenset[int]


@dataclass(frozen=True)
class DepartmentDeviceFilterSelection:
    """Нормализованный выбор узлов единого дерева канбана."""

    visible_departments: tuple
    visible_devices: tuple
    selected_department_ids: tuple[int, ...]
    selected_device_ids: tuple[int, ...]
    branch_ids: frozenset[int]

    @property
    def selected_ids(self):
        """Обратная совместимость с прежним контекстом подразделений."""

        return self.selected_department_ids

    @property
    def selected_count(self):
        return len(self.selected_department_ids) + len(self.selected_device_ids)


def _positive_unique_ids(raw_values):
    result = []
    seen = set()
    for raw_value in raw_values:
        try:
            department_id = int(raw_value)
        except (TypeError, ValueError):
            continue
        if department_id <= 0 or department_id in seen:
            continue
        seen.add(department_id)
        result.append(department_id)
    return result


def _department_maps(departments):
    department_by_id = {department.id: department for department in departments}
    parent_by_id = {
        department.id: (
            department.parent_id
            if department.parent_id in department_by_id
            else None
        )
        for department in departments
    }
    children_by_parent = {}
    for department in departments:
        parent_id = parent_by_id[department.id]
        children_by_parent.setdefault(parent_id, []).append(department.id)
    return department_by_id, parent_by_id, children_by_parent


def normalize_department_ids(raw_values, visible_departments):
    """Оставляет только разрешенные корни и поглощает потомков их предками."""

    departments = tuple(visible_departments)
    department_by_id, parent_by_id, _children_by_parent = _department_maps(
        departments
    )
    requested_ids = [
        department_id
        for department_id in _positive_unique_ids(raw_values)
        if department_id in department_by_id
    ]
    requested_set = set(requested_ids)
    normalized_ids = []

    for department_id in requested_ids:
        ancestor_id = parent_by_id.get(department_id)
        visited = set()
        absorbed = False
        while ancestor_id is not None and ancestor_id not in visited:
            if ancestor_id in requested_set:
                absorbed = True
                break
            visited.add(ancestor_id)
            ancestor_id = parent_by_id.get(ancestor_id)
        if not absorbed:
            normalized_ids.append(department_id)

    return tuple(normalized_ids)


def normalize_device_ids(raw_values, visible_devices):
    """Оставляет только уникальные изделия из уже разрешенной выборки."""

    visible_ids = {device.id for device in visible_devices}
    return tuple(
        device_id
        for device_id in _positive_unique_ids(raw_values)
        if device_id in visible_ids
    )


def expand_department_branches(selected_ids, visible_departments):
    """Возвращает выбранные разрешенные узлы и всех их разрешенных потомков."""

    departments = tuple(visible_departments)
    department_by_id, _parent_by_id, children_by_parent = _department_maps(
        departments
    )
    branch_ids = set()
    stack = [
        department_id
        for department_id in selected_ids
        if department_id in department_by_id
    ]
    while stack:
        department_id = stack.pop()
        if department_id in branch_ids:
            continue
        branch_ids.add(department_id)
        stack.extend(children_by_parent.get(department_id, ()))
    return frozenset(branch_ids)


def resolve_department_selection(raw_values, visible_departments):
    """Материализует разрешенный queryset один раз и строит состояние фильтра."""

    departments = tuple(visible_departments)
    selected_ids = normalize_department_ids(raw_values, departments)
    return DepartmentFilterSelection(
        visible_departments=departments,
        selected_ids=selected_ids,
        branch_ids=expand_department_branches(selected_ids, departments),
    )


def resolve_department_device_selection(
    raw_department_values,
    raw_device_values,
    visible_departments,
    visible_devices,
):
    """Нормализует оба типа узлов строго внутри разрешенных наборов."""

    departments = tuple(visible_departments)
    devices = tuple(visible_devices)
    selected_department_ids = normalize_department_ids(
        raw_department_values,
        departments,
    )
    return DepartmentDeviceFilterSelection(
        visible_departments=departments,
        visible_devices=devices,
        selected_department_ids=selected_department_ids,
        selected_device_ids=normalize_device_ids(raw_device_values, devices),
        branch_ids=expand_department_branches(
            selected_department_ids,
            departments,
        ),
    )


def department_search_ids(query, visible_departments):
    """Ищет совпавшие разрешенные подразделения вместе с их потомками."""

    departments = tuple(visible_departments)
    normalized_query = (query or "").strip().casefold()
    if not normalized_query:
        return frozenset()

    matched_ids = {
        department.id
        for department in departments
        if normalized_query in department.name.casefold()
    }
    return expand_department_branches(matched_ids, departments)


def build_department_filter_read_model(
    visible_departments,
    selected_ids,
    visible_devices=(),
    selected_device_ids=(),
):
    """Строит безопасный DFS-список узлов без дополнительных запросов к БД."""

    departments = tuple(visible_departments)
    department_by_id, parent_by_id, children_by_parent = _department_maps(
        departments
    )
    selected_set = {
        department_id
        for department_id in selected_ids
        if department_id in department_by_id
    }
    devices = tuple(visible_devices)
    visible_device_ids = {device.id for device in devices}
    selected_device_set = {
        device_id
        for device_id in selected_device_ids
        if device_id in visible_device_ids
    }
    devices_by_department = {}
    for device in devices:
        if device.department_id not in department_by_id:
            continue
        devices_by_department.setdefault(device.department_id, []).append(device)

    ancestor_ids = set()
    for department_id in selected_set:
        ancestor_id = parent_by_id.get(department_id)
        visited = set()
        while ancestor_id is not None and ancestor_id not in visited:
            ancestor_ids.add(ancestor_id)
            visited.add(ancestor_id)
            ancestor_id = parent_by_id.get(ancestor_id)
    for device in devices:
        if device.id not in selected_device_set:
            continue
        ancestor_id = device.department_id
        visited = set()
        while ancestor_id is not None and ancestor_id not in visited:
            ancestor_ids.add(ancestor_id)
            visited.add(ancestor_id)
            ancestor_id = parent_by_id.get(ancestor_id)

    def sort_ids(department_ids):
        return sorted(
            department_ids,
            key=lambda department_id: (
                department_by_id[department_id].name.casefold(),
                department_id,
            ),
        )

    rows = []
    visited = set()

    def append_branch(department_id, level):
        if department_id in visited:
            return
        visited.add(department_id)
        child_ids = sort_ids(children_by_parent.get(department_id, ()))
        child_devices = sorted(
            devices_by_department.get(department_id, ()),
            key=lambda device: (
                device.name.casefold(),
                device.inventory_number or "",
                device.id,
            ),
        )
        department = department_by_id[department_id]
        is_selected = department_id in selected_set
        rows.append(
            {
                "kind": "department",
                "key": f"department:{department_id}",
                "parent_key": (
                    f"department:{parent_by_id[department_id]}"
                    if parent_by_id[department_id] is not None
                    else None
                ),
                "department_id": department_id,
                "id": department_id,
                "label": department.name,
                "parent_id": parent_by_id[department_id],
                "level": level,
                "has_children": bool(child_ids or child_devices),
                "selected": is_selected,
                "ancestor_of_selected": (
                    department_id in ancestor_ids and not is_selected
                ),
            }
        )
        for child_id in child_ids:
            append_branch(child_id, level + 1)
        for device in child_devices:
            rows.append(
                {
                    "kind": "device",
                    "key": f"device:{device.id}",
                    "parent_key": f"department:{department_id}",
                    "device_id": device.id,
                    "id": device.id,
                    "label": str(device),
                    "parent_id": department_id,
                    "level": level + 1,
                    "has_children": False,
                    "selected": device.id in selected_device_set,
                    "ancestor_of_selected": False,
                }
            )

    for root_id in sort_ids(children_by_parent.get(None, ())):
        append_branch(root_id, 0)

    # Защита от поврежденного цикла: разрешенный узел не теряется и не вызывает
    # бесконечную рекурсию, а становится дополнительным корнем read model.
    for department_id in sort_ids(set(department_by_id) - visited):
        append_branch(department_id, 0)

    return tuple(rows)
