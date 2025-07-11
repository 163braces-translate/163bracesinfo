# Generated by Django 5.1.9 on 2025-06-09 14:04

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("home", "0009_remove_homepage_bg_display_mode_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="homepage",
            name="bg_display_mode",
            field=models.CharField(
                choices=[
                    ("cover", "擴展填滿 (cover)"),
                    ("contain", "等比例縮放 (contain)"),
                    ("repeat", "重複填滿 (repeat)"),
                    ("no-repeat", "原圖不重複 (no-repeat)"),
                ],
                default="cover",
                max_length=20,
                verbose_name="背景顯示方式",
            ),
        ),
        migrations.AddField(
            model_name="homepage",
            name="bg_opacity",
            field=models.IntegerField(
                default=40, help_text="遮罩透明度（0~100，0=完全透明，100=完全不透明）"
            ),
        ),
    ]
