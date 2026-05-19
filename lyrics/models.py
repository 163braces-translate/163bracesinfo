from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.fields import StreamField

from myproject.utils.models import BasePage
from .blocks import LyricsStreamBlock


class LyricsPage(BasePage):
    """
    雙欄歌詞頁。同一筆資料同時支援：
      - 雙語對照（左=中、右=英）
      - 對唱模式（左=Voice A、右=Voice B）
      - 單欄模式（只渲染左欄）
    """
    template = "pages/lyrics_page.html"

    # ── 歌曲基本資訊 ─────────────────────────────────────────────
    artist = models.CharField("演唱者", max_length=255, blank=True)
    composer = models.CharField("作曲", max_length=255, blank=True)
    lyricist = models.CharField("作詞", max_length=255, blank=True)
    release_year = models.PositiveIntegerField("發行年份", null=True, blank=True)

    # ── 顯示模式 ────────────────────────────────────────────────
    MODE_BILINGUAL = "bilingual"
    MODE_DUET = "duet"
    MODE_SINGLE = "single"
    MODE_CHOICES = [
        (MODE_BILINGUAL, "雙語對照（中／英）"),
        (MODE_DUET, "對唱模式（A／B）"),
        (MODE_SINGLE, "單欄（只用左欄）"),
    ]
    display_mode = models.CharField(
        "顯示模式",
        max_length=20,
        choices=MODE_CHOICES,
        default=MODE_BILINGUAL,
    )
    left_label = models.CharField(
        "左欄標題", max_length=50, blank=True, default="中文",
        help_text="顯示在左欄上方，例：中文／Voice A／主唱",
    )
    right_label = models.CharField(
        "右欄標題", max_length=50, blank=True, default="English",
        help_text="顯示在右欄上方。單欄模式時忽略。",
    )

    # ── 排版控制（admin GUI 可調）────────────────────────────────
    line_height = models.FloatField(
        "行距倍數",
        default=1.8,
        validators=[MinValueValidator(1.0), MaxValueValidator(3.5)],
        help_text="1.0 = 緊密；1.8 = 標準；2.5 以上 = 寬鬆。可填小數，例：1.6",
    )
    line_gap = models.PositiveIntegerField(
        "歌詞行間距 (px)",
        default=8,
        validators=[MinValueValidator(0), MaxValueValidator(48)],
        help_text="兩行歌詞之間的額外空隙。設 0 就只靠 line-height 撐開。",
    )
    section_gap = models.PositiveIntegerField(
        "段落間距 (px)",
        default=32,
        validators=[MinValueValidator(8), MaxValueValidator(96)],
        help_text="主歌、副歌等段落之間的距離。",
    )
    column_gap = models.PositiveIntegerField(
        "左右欄間距 (px)",
        default=32,
        validators=[MinValueValidator(0), MaxValueValidator(120)],
        help_text="左右兩欄之間的水平距離。",
    )
    font_size = models.PositiveIntegerField(
        "歌詞字級 (px)",
        default=18,
        validators=[MinValueValidator(12), MaxValueValidator(32)],
    )

    # ── 歌詞主體 ────────────────────────────────────────────────
    body = StreamField(
        LyricsStreamBlock(),
        use_json_field=True,
        blank=True,
        verbose_name="歌詞內容",
    )

    # ── Admin 編輯介面 ──────────────────────────────────────────
    content_panels = BasePage.content_panels + [
        MultiFieldPanel(
            [
                FieldPanel("artist"),
                FieldPanel("composer"),
                FieldPanel("lyricist"),
                FieldPanel("release_year"),
            ],
            heading="歌曲資訊",
        ),
        MultiFieldPanel(
            [
                FieldPanel("display_mode"),
                FieldPanel("left_label"),
                FieldPanel("right_label"),
            ],
            heading="顯示模式",
        ),
        MultiFieldPanel(
            [
                FieldPanel("font_size"),
                FieldPanel("line_height"),
                FieldPanel("line_gap"),
                FieldPanel("section_gap"),
                FieldPanel("column_gap"),
            ],
            heading="排版調整",
            classname="collapsible collapsed",
        ),
        FieldPanel("body"),
    ]

    class Meta:
        verbose_name = "歌詞頁"
        verbose_name_plural = "歌詞頁"