from django.db import migrations


def initialize_main_board(apps, schema_editor):
    Board = apps.get_model("workorders", "Board")
    KanbanColumnConfig = apps.get_model("workorders", "KanbanColumnConfig")
    WorkOrder = apps.get_model("workorders", "WorkOrder")

    main_board, created = Board.objects.get_or_create(
        slug="main",
        defaults={"title": "Основная доска"}
    )

    # Link all orphan columns to the main board
    KanbanColumnConfig.objects.filter(board__isnull=True).update(board=main_board)
    
    # Link all orphan workorders to the main board
    WorkOrder.objects.filter(board__isnull=True).update(board=main_board)


def reverse_main_board(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("workorders", "0009_alter_kanbancolumnconfig_code_board_and_more"),
    ]

    operations = [
        migrations.RunPython(initialize_main_board, reverse_main_board),
    ]
