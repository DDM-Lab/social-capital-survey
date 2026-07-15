from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("survey", "0002_answer_value_json_question_config_json"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="answer",
            name="grid_col",
        ),
        migrations.RemoveField(
            model_name="answer",
            name="grid_row",
        ),
        migrations.RemoveField(
            model_name="answer",
            name="likert_value",
        ),
        migrations.RemoveField(
            model_name="answer",
            name="text_value",
        ),
        migrations.RemoveField(
            model_name="question",
            name="grid_cols",
        ),
        migrations.RemoveField(
            model_name="question",
            name="grid_rows",
        ),
        migrations.RemoveField(
            model_name="question",
            name="likert_max",
        ),
        migrations.RemoveField(
            model_name="question",
            name="likert_max_label",
        ),
        migrations.RemoveField(
            model_name="question",
            name="likert_min",
        ),
        migrations.RemoveField(
            model_name="question",
            name="likert_min_label",
        ),
    ]
