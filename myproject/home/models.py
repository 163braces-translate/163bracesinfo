from django.db import models
from django.db import models
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel
from wagtail.search import index

from wagtail.fields import StreamField
from myproject.utils.blocks import StoryBlock, InternalLinkBlock, CaptionedImageBlock
from myproject.utils.models import BasePage
from wagtail_color_panel.blocks import NativeColorBlock



class HomePage(BasePage):
    template = "pages/home_page.html"
    introduction = models.TextField(blank=True)
    hero_cta = StreamField(
        [("link", InternalLinkBlock())],
        blank=True,
        min_num=0,
        max_num=5,
    )
    body = StreamField(StoryBlock())
    featured_section_title = models.TextField(blank=True)

    search_fields = BasePage.search_fields + [index.SearchField("introduction")]

    # 測試上傳背景圖片
    hero_image = StreamField(
        [("image", CaptionedImageBlock())],
        blank=True,
        max_num=1,   # 只允許一張圖，模仿代表圖行為
        use_json_field=True  # Wagtail 4+ 必須加這個參數
    )
    
    # 新增「顯示方式」欄位
    BG_DISPLAY_CHOICES = [
        ('cover', '擴展填滿 (cover)'),
        ('contain', '等比例縮放 (contain)'),
        ('repeat', '重複填滿 (repeat)'),
        ('no-repeat', '原圖不重複 (no-repeat)'),
    ]
    bg_display_mode = models.CharField(
        max_length=20,
        choices=BG_DISPLAY_CHOICES,
        default='cover',
        verbose_name="背景顯示方式"
    )

    # 新增「透明度」欄位
    bg_opacity = models.IntegerField(
        default=40,
        help_text="遮罩透明度（0~100，0=完全透明，100=完全不透明）"
    )

    @property
    def bg_opacity_mask(self):
        # 回傳 0~1 的小數，給 rgba 用
        return round(1 - (self.bg_opacity / 100), 2)


    content_panels = BasePage.content_panels + [
        FieldPanel("introduction"),
        FieldPanel("hero_cta"),
        FieldPanel("body"),
        MultiFieldPanel(
            [
                FieldPanel("featured_section_title", heading="Title"),
                InlinePanel(
                    "page_related_pages",
                    label="Pages",
                    max_num=12,
                ),
            ],
            heading="Featured section",
        ),
        FieldPanel("hero_image"),
        FieldPanel("bg_display_mode"),
        FieldPanel("bg_opacity"),
    ]
