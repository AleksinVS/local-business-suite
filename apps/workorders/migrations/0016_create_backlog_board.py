from django.db import migrations


DEFAULT_COLUMNS = [
    ("new", "Новые", 10, ["new"]),
    ("in_progress", "В работе", 20, ["accepted", "in_progress", "on_hold"]),
    ("done", "Выполнены", 30, ["resolved"]),
    ("archive", "Архив", 40, ["closed", "cancelled"]),
]


def create_backlog_board(apps, schema_editor):
    Board = apps.get_model("workorders", "Board")
    KanbanColumnConfig = apps.get_model("workorders", "KanbanColumnConfig")
    Group = apps.get_model("auth", "Group")

    board, _ = Board.objects.get_or_create(
        slug="backlog",
        defaults={"title": "Техподдержка"},
    )
    if board.title != "Техподдержка":
        board.title = "Техподдержка"
        board.save(update_fields=["title"])

    groups = [
        Group.objects.get_or_create(name=name)[0]
        for name in ("manager", "technician", "customer")
    ]
    board.allowed_groups.add(*groups)

    for code, title, position, statuses in DEFAULT_COLUMNS:
        KanbanColumnConfig.objects.update_or_create(
            board=board,
            code=code,
            defaults={
                "title": title,
                "position": position,
                "statuses": statuses,
            },
        )


def reverse_backlog_board(apps, schema_editor):
    Board = apps.get_model("workorders", "Board")
    Board.objects.filter(slug="backlog").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("workorders", "0015_alter_kanbancolumnconfig_wip_limit_and_more"),
    ]

    operations = [
        migrations.RunPython(create_backlog_board, reverse_backlog_board),
    ]
