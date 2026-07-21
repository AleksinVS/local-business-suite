from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("workorders", "0010_initialize_main_board"),
    ]

    operations = [
        migrations.AlterField(
            model_name="kanbancolumnconfig",
            name="board",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="columns",
                to="workorders.board",
                verbose_name="Доска",
            ),
        ),
        migrations.AlterField(
            model_name="workorder",
            name="board",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="workorders",
                to="workorders.board",
                verbose_name="Доска",
            ),
        ),
    ]
