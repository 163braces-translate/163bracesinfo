# Generated by Django 5.1.9 on 2025-06-07 16:21

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "performances",
            "0004_alter_performance_city_alter_performance_event_type_and_more",
        ),
    ]

    operations = [
        migrations.CreateModel(
            name="City",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=50, verbose_name="城市")),
            ],
        ),
        migrations.CreateModel(
            name="EventType",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=50, verbose_name="類型")),
            ],
        ),
        migrations.AlterField(
            model_name="performance",
            name="event_name",
            field=models.CharField(max_length=255, verbose_name="表演名稱"),
        ),
        migrations.AlterField(
            model_name="performance",
            name="city",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, to="performances.city"
            ),
        ),
        migrations.AlterField(
            model_name="performance",
            name="event_type",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, to="performances.eventtype"
            ),
        ),
    ]
