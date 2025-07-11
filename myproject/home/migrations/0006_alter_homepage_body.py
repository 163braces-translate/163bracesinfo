# Generated by Django 5.1.9 on 2025-06-05 18:07

import wagtail.fields
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("home", "0005_alter_homepage_body"),
    ]

    operations = [
        migrations.AlterField(
            model_name="homepage",
            name="body",
            field=wagtail.fields.StreamField(
                [("section", 4), ("cta", 14), ("statistics", 18)],
                block_lookup={
                    0: (
                        "wagtail.blocks.CharBlock",
                        (),
                        {
                            "form_classname": "title",
                            "icon": "title",
                            "template": "components/streamfield/blocks/heading2_block.html",
                        },
                    ),
                    1: (
                        "wagtail.blocks.RichTextBlock",
                        (),
                        {
                            "features": [
                                "bold",
                                "italic",
                                "link",
                                "ol",
                                "ul",
                                "h3",
                                "embed",
                            ],
                            "template": "components/streamfield/blocks/paragraph_block.html",
                        },
                    ),
                    2: (
                        "wagtail_color_panel.blocks.NativeColorBlock",
                        (),
                        {"default": "#000000", "label": "選擇顏色"},
                    ),
                    3: (
                        "wagtail.blocks.StreamBlock",
                        [[("paragraph", 1), ("color", 2)]],
                        {},
                    ),
                    4: (
                        "wagtail.blocks.StructBlock",
                        [[("heading", 0), ("content", 3)]],
                        {},
                    ),
                    5: (
                        "wagtail.blocks.CharBlock",
                        (),
                        {"form_classname": "title", "icon": "title", "required": True},
                    ),
                    6: ("wagtail.blocks.PageChooserBlock", (), {}),
                    7: (
                        "wagtail.blocks.CharBlock",
                        (),
                        {
                            "help_text": "Leave blank to use page's listing title.",
                            "required": False,
                        },
                    ),
                    8: (
                        "wagtail.blocks.StructBlock",
                        [[("page", 6), ("title", 7)]],
                        {},
                    ),
                    9: ("wagtail.blocks.URLBlock", (), {}),
                    10: ("wagtail.blocks.CharBlock", (), {}),
                    11: (
                        "wagtail.blocks.StructBlock",
                        [[("link", 9), ("title", 10)]],
                        {},
                    ),
                    12: (
                        "wagtail.blocks.StreamBlock",
                        [[("internal", 8), ("external", 11)]],
                        {},
                    ),
                    13: ("wagtail.blocks.TextBlock", (), {"required": False}),
                    14: (
                        "wagtail.blocks.StructBlock",
                        [[("heading", 5), ("link", 12), ("description", 13)]],
                        {},
                    ),
                    15: (
                        "wagtail.blocks.BooleanBlock",
                        (),
                        {
                            "help_text": "If checked, the heading will be hidden from view and avaliable to screen-readers only.",
                            "label": "Screen reader only label",
                            "required": False,
                        },
                    ),
                    16: (
                        "wagtail.snippets.blocks.SnippetChooserBlock",
                        ("utils.Statistic",),
                        {},
                    ),
                    17: (
                        "wagtail.blocks.ListBlock",
                        (16,),
                        {"max_num": 3, "min_num": 3},
                    ),
                    18: (
                        "wagtail.blocks.StructBlock",
                        [[("heading", 5), ("sr_only_label", 15), ("statistics", 17)]],
                        {},
                    ),
                },
            ),
        ),
    ]
