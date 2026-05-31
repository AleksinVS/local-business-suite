from collections import Counter, defaultdict

from apps.core.models import Department

from .models import WorkOrderStatus


ACTIVE_STATUSES = {
    WorkOrderStatus.NEW,
    WorkOrderStatus.ACCEPTED,
    WorkOrderStatus.IN_PROGRESS,
    WorkOrderStatus.ON_HOLD,
    WorkOrderStatus.RESOLVED,
}


def _empty_node(
    *,
    node_id,
    parent_id,
    level,
    node_type,
    label,
    subtitle="",
    department_id=None,
    device_id=None,
    workorder=None,
    sort_label="",
    sort_index=0,
):
    return {
        "id": node_id,
        "parent_id": parent_id,
        "level": level,
        "aria_level": level + 1,
        "node_type": node_type,
        "label": label,
        "subtitle": subtitle,
        "department_id": department_id,
        "device_id": device_id,
        "workorder": workorder,
        "count": 0,
        "active_count": 0,
        "status_counts": Counter(),
        "status_chips": [],
        "has_children": False,
        "can_create_here": False,
        "sort_label": (sort_label or label).lower(),
        "sort_index": sort_index,
    }


def _device_subtitle(device):
    parts = []
    if getattr(device, "model", ""):
        parts.append(device.model)
    if getattr(device, "serial_number", ""):
        parts.append(f"SN {device.serial_number}")
    if getattr(device, "inventory_number", ""):
        parts.append(f"инв. {device.inventory_number}")
    return " · ".join(parts)


def build_workorder_tree(queryset, *, can_create_workorder=False):
    workorders = list(queryset)
    status_labels = dict(WorkOrderStatus.choices)
    status_order = [status for status, _label in WorkOrderStatus.choices]

    departments = {
        department.id: department
        for department in Department.objects.select_related("parent").order_by(
            "parent_id", "name", "id"
        )
    }
    path_cache = {}

    def department_path(department_id):
        if department_id in path_cache:
            return path_cache[department_id]
        department = departments.get(department_id)
        if department is None:
            path_cache[department_id] = []
            return []
        if department.parent_id:
            path = [*department_path(department.parent_id), department_id]
        else:
            path = [department_id]
        path_cache[department_id] = path
        return path

    nodes = {}
    children = defaultdict(list)

    def ensure_node(**kwargs):
        node_id = kwargs["node_id"]
        if node_id not in nodes:
            nodes[node_id] = _empty_node(**kwargs)
            parent_id = kwargs.get("parent_id")
            if parent_id:
                children[parent_id].append(node_id)
        return nodes[node_id]

    def add_count(node, status):
        node["count"] += 1
        if status in ACTIVE_STATUSES:
            node["active_count"] += 1
        node["status_counts"][status] += 1

    root = ensure_node(
        node_id="organization:root",
        parent_id="",
        level=0,
        node_type="organization",
        label="Организация",
        sort_label="",
    )

    for sort_index, workorder in enumerate(workorders):
        add_count(root, workorder.status)
        parent_node_id = root["id"]
        path = department_path(workorder.department_id)

        for depth, department_id in enumerate(path, start=1):
            department = departments[department_id]
            department_node = ensure_node(
                node_id=f"department:{department_id}",
                parent_id=parent_node_id,
                level=depth,
                node_type="department",
                label=department.name,
                department_id=department_id,
                sort_label=department.name,
            )
            add_count(department_node, workorder.status)
            parent_node_id = department_node["id"]

        department_id = workorder.department_id
        if workorder.device_id:
            device_node = ensure_node(
                node_id=f"device:{department_id}:{workorder.device_id}",
                parent_id=parent_node_id,
                level=len(path) + 1,
                node_type="device",
                label=workorder.device.name,
                subtitle=_device_subtitle(workorder.device),
                department_id=department_id,
                device_id=workorder.device_id,
                sort_label=workorder.device.name,
            )
        else:
            device_node = ensure_node(
                node_id=f"device:{department_id}:none",
                parent_id=parent_node_id,
                level=len(path) + 1,
                node_type="device",
                label="Без привязки к медизделию",
                subtitle="Заявки по отделению без конкретного изделия",
                department_id=department_id,
                sort_label="",
            )
        add_count(device_node, workorder.status)

        ensure_node(
            node_id=f"workorder:{workorder.pk}",
            parent_id=device_node["id"],
            level=len(path) + 2,
            node_type="workorder",
            label=f"{workorder.number}. {workorder.title}",
            subtitle=workorder.description,
            department_id=department_id,
            device_id=workorder.device_id,
            workorder=workorder,
            sort_label=workorder.title,
            sort_index=sort_index,
        )
        workorder_node = nodes[f"workorder:{workorder.pk}"]
        add_count(workorder_node, workorder.status)

    for node in nodes.values():
        node["has_children"] = bool(children.get(node["id"]))
        node["can_create_here"] = (
            can_create_workorder and node["node_type"] in {"department", "device"}
        )
        node["status_chips"] = [
            {
                "status": status,
                "label": status_labels.get(status, status),
                "count": node["status_counts"][status],
            }
            for status in status_order
            if node["status_counts"].get(status)
        ]

    def sort_key(node_id):
        node = nodes[node_id]
        if node["node_type"] == "workorder":
            return (3, node["sort_index"])
        if node["node_type"] == "device" and node["device_id"] is None:
            return (2, "яяя", node["sort_index"])
        group = {"department": 1, "device": 2}.get(node["node_type"], 0)
        return (group, node["sort_label"], node["sort_index"])

    rows = []

    def append_node(node_id):
        rows.append(nodes[node_id])
        for child_id in sorted(children.get(node_id, []), key=sort_key):
            append_node(child_id)

    append_node(root["id"])
    return {
        "rows": rows,
        "total_count": root["count"],
        "active_count": root["active_count"],
        "is_empty": root["count"] == 0,
    }
