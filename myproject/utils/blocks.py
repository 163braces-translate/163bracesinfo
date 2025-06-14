from collections import defaultdict

from django.core.exceptions import ValidationError
from django.forms.utils import ErrorList
from wagtail import blocks
from wagtail.blocks.struct_block import StructBlockValidationError
from wagtail.documents.blocks import DocumentChooserBlock
from wagtail.images.blocks import ImageBlock, ImageChooserBlock
from wagtail.snippets.blocks import SnippetChooserBlock
from wagtail.contrib.table_block.blocks import TableBlock

from wagtail_color_panel.blocks import NativeColorBlock

from myproject.utils.struct_values import CardStructValue, LinkStructValue


class AccordionBlock(blocks.StructBlock):
    title = blocks.CharBlock(max_length=255)
    content = blocks.RichTextBlock()

    class Meta:
        label = "Section"
        icon = "title"


class AccordionBlock(blocks.StructBlock):
    heading = blocks.ListBlock(AccordionBlock())
    list = blocks.ListBlock(AccordionBlock())

    class Meta:
        icon = "list-ol"
        template = "components/accordion/accordion.html"


class CaptionedImageBlock(blocks.StructBlock):
    image = ImageChooserBlock()
    image_alt_text = blocks.CharBlock(
        required=False,
        help_text="If left blank, the image's global alt text will be used.",
    )
    caption = blocks.CharBlock(required=False)

    class Meta:
        icon = "image"
        template = "components/streamfield/blocks/image_block.html"


class InternalLinkBlock(blocks.StructBlock):
    page = blocks.PageChooserBlock()
    title = blocks.CharBlock(
        required=False,
        help_text="Leave blank to use page's listing title.",
    )

    show_children = blocks.BooleanBlock(
        required=False,
        default=False,
        help_text="Show child pages in dropdown menu",
    )
    max_children_depth = blocks.IntegerBlock(
        required=False,
        default=1,
        min_value=1,
        max_value=3,
        help_text="Maximum depth of child pages to show (1-3 levels)",
    )

    class Meta:
        icon = "link"
        value_class = LinkStructValue


class ArticlePageLinkBlock(InternalLinkBlock):
    page = blocks.PageChooserBlock(
        page_type="news.ArticlePage",
    )


class ExternalLinkBlock(blocks.StructBlock):
    link = blocks.URLBlock()
    title = blocks.CharBlock()

    class Meta:
        icon = "link"
        value_class = LinkStructValue


class LinkStreamBlock(blocks.StreamBlock):
    """
    StreamBlock that allows editors to add a single link of type internal or external.
    """

    internal = InternalLinkBlock()
    external = ExternalLinkBlock()

    class Meta:
        icon = "link"
        label = "Link"
        min_num = 1
        max_num = 1


class QuoteBlock(blocks.StructBlock):
    quote = blocks.TextBlock(form_classname="title")
    attribution = blocks.CharBlock(required=False)

    class Meta:
        icon = "openquote"
        template = "components/streamfield/blocks/quote_block.html"


class CardBlock(blocks.StructBlock):
    heading = blocks.CharBlock(max_length=255)
    description = blocks.RichTextBlock(required=False, features=["bold", "italic"])
    link = LinkStreamBlock(required=False, min_num=0)

    class Meta:
        icon = "form"
        template = "components/streamfield/blocks/card_block.html"
        label = "Card"
        value_class = CardStructValue


class FeaturedArticleBlock(blocks.StructBlock):
    link = ArticlePageLinkBlock()
    image = ImageBlock(
        required=False,
        help_text="Set to override the image of the chosen article page.",
    )
    description = blocks.TextBlock(
        max_length=255,
        required=False,
        help_text="Choose to override a page's listing summary or introduction.",
    )
    cta_text = blocks.CharBlock(
        max_length=255,
        blank=False,
        help_text="This is the cta link text. This will automatically redirect to the article page.",
    )
    left_aligned = blocks.BooleanBlock(
        required=False,
        help_text="If checked, the text will be left-aligned.",
    )

    class Meta:
        icon = "doc-full"
        template = "components/streamfield/blocks/feature_block.html"


class BaseSectionBlock(blocks.StructBlock):
    heading = blocks.CharBlock(
        form_classname="title", icon="title", required=True
    )  # Should use H2s only
    sr_only_label = blocks.BooleanBlock(
        required=False,
        label="Screen reader only label",
        help_text="If checked, the heading will be hidden from view and avaliable to screen-readers only.",
    )

    class Meta:
        abstract = True
        icon = "title"


class StatisticSectionBlock(BaseSectionBlock):
    statistics = blocks.ListBlock(
        SnippetChooserBlock("utils.Statistic"),
        max_num=3,
        min_num=3,
    )

    class Meta:
        icon = "snippet"
        template = "components/streamfield/blocks/stat_block.html"


class CTASectionBlock(blocks.StructBlock):
    heading = blocks.CharBlock(form_classname="title", icon="title", required=True)
    link = LinkStreamBlock()
    description = blocks.TextBlock(required=False)

    class Meta:
        icon = "link"
        label = "CTA"
        template = "components/streamfield/blocks/cta_block.html"


class BaseCardSectionBlock(BaseSectionBlock):
    cards = blocks.ListBlock(
        CardBlock(),
        max_num=6,
        min_num=3,
        label="Card",
    )

    class Meta:
        abstract = True
        icon = "form"


class CardSectionBlock(BaseCardSectionBlock):
    class Meta:
        template = "components/streamfield/blocks/card_section_block.html"


class PlainCardSectionBlock(BaseCardSectionBlock):
    class Meta:
        icon = "doc-full"
        template = "components/streamfield/blocks/plain_cards_block.html"

#嵌入YT
class YouTubeEmbedBlock(blocks.StructBlock):
    title = blocks.CharBlock(
        required=False,
        help_text="影片標題（可選）"
    )
    youtube_url = blocks.URLBlock(
        help_text="請貼上 YouTube 影片網址（支援 youtube.com 和 youtu.be 格式）"
    )
    
    def get_context(self, value, parent_context=None):
        context = super().get_context(value, parent_context)
        
        # 從 YouTube URL 中提取影片 ID
        import re
        url = value.get('youtube_url', '')
        
        # 支援多種 YouTube URL 格式
        patterns = [
            # 標準格式：https://www.youtube.com/watch?v=VIDEO_ID
            r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]+)',
            # 短網址格式：https://youtu.be/VIDEO_ID 或 https://youtu.be/VIDEO_ID?si=xxx
            r'(?:https?://)?(?:www\.)?youtu\.be/([a-zA-Z0-9_-]+)(?:\?.*)?',
            # 嵌入格式：https://www.youtube.com/embed/VIDEO_ID
            r'(?:https?://)?(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]+)',
        ]
        
        video_id = None
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                video_id = match.group(1)
                break
        
        context['video_id'] = video_id
        context['original_url'] = url
        return context

    class Meta:
        icon = "media"
        label = "YouTube 影片"
        template = "components/streamfield/blocks/youtube_embed.html"

#YT結束

class SectionBlocks(blocks.StreamBlock):
    paragraph = blocks.RichTextBlock(
        features=["bold", "italic", "link", "ol", "ul", "h3", "embed"],
        template="components/streamfield/blocks/paragraph_block.html",
    )
    youtube = YouTubeEmbedBlock()


class SectionBlock(blocks.StructBlock):
    heading = blocks.CharBlock(
        form_classname="title",
        icon="title",
        required = False,
        template="components/streamfield/blocks/heading2_block.html",
    )
    content = SectionBlocks()

    class Meta:
        icon = "doc-full"
        template = "components/streamfield/blocks/section_block.html"


class StoryBlock(blocks.StreamBlock):
    section = SectionBlock()
    cta = CTASectionBlock()
    statistics = StatisticSectionBlock()

    class Meta:
        template = "components/streamfield/stream_block.html"
