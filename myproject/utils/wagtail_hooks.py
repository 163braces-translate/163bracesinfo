import wagtail.admin.rich_text.editors.draftail.features as draftail_features
from wagtail import hooks
from wagtail.admin.rich_text.converters.html_to_contentstate import (
    InlineStyleElementHandler,
)
from wagtail.rich_text import LinkHandler
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet

from myproject.utils.models import ArticleTopic, AuthorSnippet, Statistic


class ExternalLinkHandler(LinkHandler):
    identifier = "external"

    @classmethod
    def expand_db_attributes(cls, attrs):
        href = attrs["href"]

        return f'<a data-rich-text-external-link href="{href}">'


@hooks.register("register_rich_text_features")
def register_link_handler(features):
    features.register_link_type(ExternalLinkHandler)


# 文字顏色：(feature 名稱, 工具列標籤, 色碼)
# 存進資料庫為 <span class="text-color-xxx">，前台樣式在 static_src/sass/main.scss
TEXT_COLORS = [
    ("text-red", "紅", "#dc2626"),
    ("text-sky", "天藍", "#0ea5e9"),
    ("text-blue", "藍", "#2563eb"),
    ("text-black", "黑", "#000000"),
    ("text-white", "白", "#ffffff"),
]


@hooks.register("register_rich_text_features")
def register_text_color_features(features):
    for feature_name, label, hex_color in TEXT_COLORS:
        type_ = feature_name.upper().replace("-", "_")
        css_class = f"text-color-{feature_name.removeprefix('text-')}"

        editor_style = {"color": hex_color}
        if hex_color == "#ffffff":
            # 白字在編輯器白底上看不到，加深色底方便辨識
            editor_style["backgroundColor"] = "#6b7280"

        features.register_editor_plugin(
            "draftail",
            feature_name,
            draftail_features.InlineStyleFeature(
                {
                    "type": type_,
                    "label": label,
                    "description": f"文字顏色：{label}",
                    "style": editor_style,
                }
            ),
        )
        features.register_converter_rule(
            "contentstate",
            feature_name,
            {
                "from_database_format": {
                    f"span[class={css_class}]": InlineStyleElementHandler(type_)
                },
                "to_database_format": {
                    "style_map": {
                        type_: {"element": "span", "props": {"class": css_class}}
                    }
                },
            },
        )


# 後台 snippet 列表的搜尋（同 performances/wagtail_hooks.py，用資料庫 icontains 查詢）
class AuthorSnippetViewSet(SnippetViewSet):
    model = AuthorSnippet
    search_backend_name = None
    search_fields = ["title", "title_en"]


class ArticleTopicViewSet(SnippetViewSet):
    model = ArticleTopic
    search_backend_name = None
    search_fields = ["title", "title_en", "slug", "slug_en"]


class StatisticViewSet(SnippetViewSet):
    model = Statistic
    search_backend_name = None
    search_fields = ["statistic", "statistic_en", "description", "description_en"]


register_snippet(AuthorSnippetViewSet)
register_snippet(ArticleTopicViewSet)
register_snippet(StatisticViewSet)
