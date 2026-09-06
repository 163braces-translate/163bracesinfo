from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import get_language
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtail.models import Orderable
from wagtail.snippets.models import register_snippet

from myproject.utils.models import BasePage
from myproject.utils.dates import weekday_labels
from wagtail.fields import RichTextField
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel

from wagtail.images import get_image_model

from django.db.models import Count, Q
from django.db.models.functions import Extract
import json
import calendar
import datetime

from wagtail.images import get_image_model


@register_snippet
class EventType(models.Model):
    name = models.CharField("類型", max_length=50)
    name_en = models.CharField("English Name", max_length=50, blank=True)
    order = models.PositiveIntegerField("排序順序", default=0)

    class Meta:
        ordering = ["order", "name"]  # 預設排序：先依 order，再依 name

    def __str__(self):
        return self.name
    
    def get_name(self, language='zh-hant'):
        if language == 'en' and self.name_en:
            return self.name_en
        return self.name

@register_snippet
class City(models.Model):
    name = models.CharField("城市", max_length=50)
    name_en = models.CharField("English Name", max_length=50, blank=True)
    order = models.PositiveIntegerField("排序順序", default=0)

    class Meta:
        ordering = ["order", "name"]  # 預設排序：先依 order，再依 name

    def __str__(self):
        return self.name
    
    def get_name(self, language='zh-hant'):
        if language == 'en' and self.name_en:
            return self.name_en
        return self.name

@register_snippet
class Performance(ClusterableModel):
    event_date = models.DateField("表演日期")
    event_name = models.CharField("表演名稱", max_length=255)
    event_name_en = models.CharField("English Event Name", max_length=255, blank=True)
    event_type = models.ForeignKey(EventType, on_delete=models.PROTECT)
    venue = models.CharField("地點", max_length=255)
    venue_en = models.CharField("English Venue", max_length=255, blank=True)
    city = models.ForeignKey(City, on_delete=models.PROTECT)

    panels = [
        MultiFieldPanel(
            [
                FieldPanel("event_date"),
                FieldPanel("event_name"),
                FieldPanel("event_name_en"),
                FieldPanel("event_type"),
            ],
            heading="演出資訊",
        ),
        MultiFieldPanel(
            [
                FieldPanel("venue"),
                FieldPanel("venue_en"),
                FieldPanel("city"),
            ],
            heading="地點",
        ),
        InlinePanel(
            "setlist",
            label="曲目",
            heading="歌單",
            help_text="從曲庫選歌；翻唱或曲庫沒有的歌，改填自訂曲名。可拖曳調整順序。",
        ),
    ]

    def __str__(self):
        return f"{self.event_date} - {self.event_name}"
    
    def get_event_name(self, language='zh-hant'):
        if language == 'en' and self.event_name_en:
            return self.event_name_en
        return self.event_name
    
    def get_venue(self, language='zh-hant'):
        if language == 'en' and self.venue_en:
            return self.venue_en
        return self.venue
    
@register_snippet
class Album(models.Model):
    name = models.CharField("專輯名稱", max_length=255)
    name_en = models.CharField("English Album Name", max_length=255, blank=True)
    order = models.PositiveIntegerField("排序順序", default=0)

    # ✨ 新增：專輯封面圖片 (非必填)
    cover_image = models.ForeignKey(
        get_image_model(),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        verbose_name="專輯封面",
        help_text="非必填。建議使用正方形圖片。",
    )

    panels = [
        FieldPanel('name'),
        FieldPanel('name_en'),
        FieldPanel('order'),
        FieldPanel('cover_image'), # ✨ 加入到管理後台面板
    ]

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name
    
    def get_name(self, language='zh-hant'):
        if language == 'en' and self.name_en:
            return self.name_en
        return self.name
    
@register_snippet
class Song(models.Model):
    title = models.CharField("歌曲名稱", max_length=255)
    title_en = models.CharField("English Title", max_length=255, blank=True)
    artist = models.CharField("演唱者", max_length=255, blank=True)
    artist_en = models.CharField("English Artist", max_length=255, blank=True)
    album = models.ForeignKey(
        Album,
        on_delete=models.PROTECT,
        default=1,  # You'll need to create "Single(單曲)" first with id=1
        verbose_name="專輯",
        help_text="選擇專輯，預設為單曲"
    )
    order = models.PositiveIntegerField("排序順序", default=0)
    
    # ✨ 新增：單曲封面圖片 (非必填)
    single_image = models.ForeignKey(
        get_image_model(),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        verbose_name="單曲封面",
        help_text="如果歌曲被設定為單曲 (Album ID=1)，可選填此欄位。",
    )

    panels = [
        FieldPanel('title'),
        FieldPanel('title_en'),
        FieldPanel('artist'),
        FieldPanel('artist_en'),
        FieldPanel('album'),
        FieldPanel('single_image'), # ✨ 加入到管理後台面板
        FieldPanel('order'),
    ]
    
    def __str__(self):
        return f"{self.title} - {self.artist}" if self.artist else self.title
    
    def get_title(self, language='zh-hant'):
        if language == 'en' and self.title_en:
            return self.title_en
        return self.title
    
    def get_artist(self, language='zh-hant'):
        if language == 'en' and self.artist_en:
            return self.artist_en
        return self.artist
    
    # ✨ 新增：獲取封面圖片的方法
    def get_cover_image(self):
        """
        如果歌曲有單曲封面，則使用單曲封面；
        否則，如果專輯有封面，則使用專輯封面。
        """
        if self.single_image:
            return self.single_image
        
        if self.album and self.album.cover_image:
            return self.album.cover_image
            
        return None # 無封面圖片
    
    class Meta:
        verbose_name = "Song"
        verbose_name_plural = "Songs"
        ordering = ['order', 'title']

class SetlistItem(Orderable):
    """
    One line of a performance's setlist.

    Either pick a song from the library, or type a title for anything the
    library does not cover — covers, guest spots, one-off songs.
    """

    performance = ParentalKey(
        Performance,
        on_delete=models.CASCADE,
        related_name="setlist",
    )
    song = models.ForeignKey(
        "performances.Song",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="setlist_items",
        verbose_name="曲庫歌曲",
        help_text="從曲庫選一首。翻唱或曲庫沒有的歌請留空，改填下方自訂曲名。",
    )
    custom_title = models.CharField(
        "自訂曲名",
        max_length=255,
        blank=True,
        help_text="只在曲庫沒有這首歌時填寫。",
    )
    note = models.CharField(
        "備註",
        max_length=255,
        blank=True,
        help_text="例如「Cover」、「Encore」、「與 XXX 合唱」。",
    )

    panels = [
        FieldPanel("song"),
        FieldPanel("custom_title"),
        FieldPanel("note"),
    ]

    class Meta(Orderable.Meta):
        verbose_name = "曲目"
        verbose_name_plural = "曲目"

    def clean(self):
        super().clean()
        if not self.song and not self.custom_title:
            raise ValidationError(
                {"song": "請從曲庫選一首歌，或在自訂曲名填入歌名。"}
            )
        if self.song and self.custom_title:
            raise ValidationError(
                {"custom_title": "已選了曲庫歌曲，請清空自訂曲名以免兩者不一致。"}
            )

    def __str__(self):
        return self.display_title

    # These read the active language themselves, so templates can use them
    # as plain attributes — Django templates cannot pass arguments.
    @property
    def display_title(self) -> str:
        if not self.song:
            return self.custom_title
        if self._english and self.song.title_en:
            return self.song.title_en
        return self.song.title

    @property
    def display_artist(self) -> str:
        """Performer, shown only for songs that are not the band's own."""
        if not self.song:
            return ""
        if self._english and self.song.artist_en:
            return self.song.artist_en
        return self.song.artist

    @property
    def _english(self) -> bool:
        return (get_language() or "").lower().startswith("en")


from .models import Performance, City, EventType

class PerformanceListPage(BasePage):
    template = "pages/performance_list_page.html"
    intro = RichTextField(blank=True)

    content_panels = BasePage.content_panels + [
        FieldPanel("intro"),
    ]

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)

        from django.utils.translation import get_language
        current_language = get_language()

        performances = Performance.objects.select_related(
            "city", "event_type"
        ).prefetch_related("setlist__song")

        # 搜尋名稱
        query = request.GET.get("q", "")
        if query:
            performances = performances.filter(event_name__icontains=query)

        # 篩選城市
        selected_cities = request.GET.getlist("city")
        if selected_cities:
            performances = performances.filter(city__id__in=selected_cities)

        # 篩選類型
        selected_types = request.GET.getlist("event_type")
        if selected_types:
            performances = performances.filter(event_type__id__in=selected_types)

        # ===== 新增：日期篩選 =====
        date_from = request.GET.get("date_from")
        date_to = request.GET.get("date_to")
        date_filter_type = request.GET.get("date_filter_type", "range")  # range, before, after

        if date_from or date_to:
            if date_filter_type == "before" and date_to:
                performances = performances.filter(event_date__lte=date_to)
            elif date_filter_type == "after" and date_from:
                performances = performances.filter(event_date__gte=date_from)
            elif date_filter_type == "range":
                if date_from:
                    performances = performances.filter(event_date__gte=date_from)
                if date_to:
                    performances = performances.filter(event_date__lte=date_to)
        # ===== 日期篩選結束 =====

        # 排序
        sort = request.GET.get("sort", "event_date_desc")
        if sort == "event_date_asc":
            performances = performances.order_by("event_date")
        else:
            performances = performances.order_by("-event_date")

        # 把結果塞回 context
        context["performances"] = performances
        context["query"] = query
        context["selected_cities"] = selected_cities
        context["selected_types"] = selected_types
        context["sort"] = sort

        # ===== 新增：日期篩選變數 =====
        context["date_from"] = date_from
        context["date_to"] = date_to  
        context["date_filter_type"] = date_filter_type
        # ===== 新增結束 =====

        # 下拉選單資料來源
        context["all_cities"] = City.objects.all().order_by("order")
        context["all_types"] = EventType.objects.all().order_by("order")
        context["current_language"] = current_language

        return context


class PerformanceStatsPage(BasePage):
    template = "pages/performance_stats_page.html"
    intro = RichTextField(blank=True)

    content_panels = BasePage.content_panels + [
        FieldPanel("intro"),
    ]

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        
        # 獲取年份參數，預設為當前年份
        from datetime import datetime
        current_year = datetime.now().year
        selected_year_param = request.GET.get("year", current_year)
        
        # 檢查是否選擇「全部時間」
        if selected_year_param == "all":
            performances = Performance.objects.all()
            year_display = "全部時間"
            selected_year_for_template = "所有"
        else:
            try:
                selected_year_int = int(selected_year_param)
                performances = Performance.objects.filter(event_date__year=selected_year_int)
                year_display = f"{selected_year_int}年"
                selected_year_for_template = str(selected_year_int)
            except (ValueError, TypeError):
                selected_year_int = current_year
                performances = Performance.objects.filter(event_date__year=selected_year_int)
                year_display = f"{selected_year_int}年"
                selected_year_for_template = str(selected_year_int)

        
        # 1. 堆疊長條圖數據：各類型每月演出數量
        monthly_data = {}
        all_types = EventType.objects.all().order_by("order")
        
        # 初始化每個月的數據
        for month in range(1, 13):
            monthly_data[month] = {}
            for event_type in all_types:
                monthly_data[month][event_type.name] = 0
        
        # 統計每月每類型的演出數量
        monthly_stats = performances.values(
            'event_date__month', 'event_type__name'
        ).annotate(count=Count('id'))
        
        for stat in monthly_stats:
            month = stat['event_date__month']
            type_name = stat['event_type__name']
            count = stat['count']
            monthly_data[month][type_name] = count
        
        # 轉換為圖表所需格式
        chart_data = {
            'labels': ['1月', '2月', '3月', '4月', '5月', '6月', 
                      '7月', '8月', '9月', '10月', '11月', '12月'],
            'datasets': []
        }
        
        # 為每個演出類型創建數據集
        colors = [ '#87CEEB', '#FFB347', '#FF7F7F', '#FFE55C', '#90EE90', '#DDA0DD',
                '#FFB6C1', '#E0E0E0', '#FFEFD5', '#F0E68C', '#E6E6FA', '#FDF5E6',
                '#F5DEB3', '#D3D3D3', '#FFE4E1', '#F0F8FF', '#FAF0E6', '#E0FFFF',
                '#FFF8DC', '#F5F5DC', '#FFFACD', '#F0FFF0', '#FFF0F5']
        
        for i, event_type in enumerate(all_types):
            dataset = {
                'label': event_type.name,
                'data': [monthly_data[month][event_type.name] for month in range(1, 13)],
                'backgroundColor': colors[i % len(colors)],
                'borderColor': colors[i % len(colors)],
                'borderWidth': 1
            }
            chart_data['datasets'].append(dataset)
        
        # 2. 圓餅圖數據：城市演出比例
        city_stats = performances.values('city__name').annotate(
            count=Count('id')
        ).order_by('-count')
        
        pie_data = {
            'labels': [stat['city__name'] for stat in city_stats],
            'datasets': [{
                'data': [stat['count'] for stat in city_stats],
                'backgroundColor': [
                '#87CEEB', '#FFB347', '#FF7F7F', '#FFE55C', '#90EE90', '#DDA0DD',
                '#FFB6C1', '#E0E0E0', '#FFEFD5', '#F0E68C', '#E6E6FA', '#FDF5E6',
                '#F5DEB3', '#D3D3D3', '#FFE4E1', '#F0F8FF', '#FAF0E6', '#E0FFFF',
                '#FFF8DC', '#F5F5DC', '#FFFACD', '#F0FFF0', '#FFF0F5'
            ][:len(city_stats)]
            }]
        }
        
        # 3. 堆疊長條圖數據：各類型的星期分布
        # iso_week_day: 1=週一 … 7=週日。用 ORM lookup 而非 strftime，
        # 這樣換資料庫也不會壞。
        # all_types 與 colors 沿用上面月度圖表的定義，讓兩張圖的
        # 類型順序與配色完全一致。
        weekday_matrix = {
            day: {event_type.name: 0 for event_type in all_types}
            for day in range(1, 8)
        }

        weekday_stats = performances.values(
            "event_date__iso_week_day", "event_type__name"
        ).annotate(count=Count("id"))

        for stat in weekday_stats:
            day = stat["event_date__iso_week_day"]
            type_name = stat["event_type__name"]
            if type_name in weekday_matrix[day]:
                weekday_matrix[day][type_name] = stat["count"]

        weekday_data = {
            "labels": weekday_labels(),
            "datasets": [
                {
                    "label": event_type.name,
                    "data": [
                        weekday_matrix[day][event_type.name] for day in range(1, 8)
                    ],
                    "backgroundColor": colors[i % len(colors)],
                    "borderColor": colors[i % len(colors)],
                    "borderWidth": 1,
                }
                for i, event_type in enumerate(all_types)
            ],
        }

        # 星期圓餅圖：各星期總場次，由多到少排序
        weekday_totals = [
            (label, sum(weekday_matrix[day].values()))
            for day, label in zip(range(1, 8), weekday_labels())
        ]
        # 沒有演出的星期不放進圓餅圖，零面積的扇形只會擠壓圖例
        weekday_totals = [item for item in weekday_totals if item[1]]
        weekday_totals.sort(key=lambda item: item[1], reverse=True)

        weekday_pie_data = {
            "labels": [label for label, _ in weekday_totals],
            "datasets": [
                {
                    "data": [count for _, count in weekday_totals],
                    "backgroundColor": colors[: len(weekday_totals)],
                }
            ],
        }

        # 獲取可選年份列表
        available_years = Performance.objects.dates('event_date', 'year').values_list(
            'event_date__year', flat=True
        ).distinct().order_by('-event_date__year')
        

        # ===== 新增：歷史演出堆疊長條圖數據 =====
        # 獲取所有演出數據，按年月和類型統計
        historical_data = {}
        all_types_for_history = EventType.objects.all().order_by("order")

        # 獲取所有年月組合
        all_performances = Performance.objects.all()
        year_months = all_performances.extra({
            'year_month': "strftime('%%Y-%%m', event_date)"
        }).values('year_month').distinct().order_by('year_month')

        # 初始化歷史數據結構
        for ym in year_months:
            year_month = ym['year_month']
            historical_data[year_month] = {}
            for event_type in all_types_for_history:
                historical_data[year_month][event_type.name] = 0

        # 統計每年月每類型的演出數量
        historical_stats = all_performances.extra({
            'year_month': "strftime('%%Y-%%m', event_date)"
        }).values('year_month', 'event_type__name').annotate(count=Count('id'))

        for stat in historical_stats:
            year_month = stat['year_month']
            type_name = stat['event_type__name']
            count = stat['count']
            if year_month in historical_data:
                historical_data[year_month][type_name] = count

        # 轉換為圖表格式
        historical_chart_data = {
            'labels': sorted(historical_data.keys()),
            'datasets': []
        }

        history_colors = [ '#87CEEB', '#FFB347', '#FF7F7F', '#FFE55C', '#90EE90', '#DDA0DD',
                '#FFB6C1', '#E0E0E0', '#FFEFD5', '#F0E68C', '#E6E6FA', '#FDF5E6',
                '#F5DEB3', '#D3D3D3', '#FFE4E1', '#F0F8FF', '#FAF0E6', '#E0FFFF',
                '#FFF8DC', '#F5F5DC', '#FFFACD', '#F0FFF0', '#FFF0F5']

        for i, event_type in enumerate(all_types_for_history):
            dataset = {
                'label': event_type.name,
                'data': [historical_data[ym][event_type.name] for ym in sorted(historical_data.keys())],
                'backgroundColor': history_colors[i % len(history_colors)],
                'borderColor': history_colors[i % len(history_colors)],
                'borderWidth': 1
            }
            historical_chart_data['datasets'].append(dataset)
        # ===== 歷史數據結束 =====

        context.update({
            'selected_year': selected_year_for_template,
            'year_display': year_display,
            'available_years': [str(year) for year in available_years],
            'chart_data': json.dumps(chart_data),
            'pie_data': json.dumps(pie_data),
            'historical_chart_data': json.dumps(historical_chart_data),
            'weekday_data': json.dumps(weekday_data),
            'weekday_pie_data': json.dumps(weekday_pie_data),
            'total_performances': performances.count(),
            'city_stats': city_stats,
        })
        
        return context
    
class ReplayPage(BasePage):
    """
    2025 Replay Page - Interactive dashboard for users to create their year-end review
    """
    template = "pages/replay_page.html"
    intro = RichTextField(blank=True)
    
    logo = models.ForeignKey(
        get_image_model(),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        verbose_name='Logo',
        help_text='Logo to display in top left corner'
    )


    content_panels = BasePage.content_panels + [
        FieldPanel('intro'),
        FieldPanel('logo'),
    ]
    
    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        
        from django.utils.translation import get_language
        current_language = get_language()
        
        # Get all songs for selection
        context['songs'] = Song.objects.all().order_by('order', 'title')
        
        # Get all 2025 performances (you can change the year as needed)
        from datetime import datetime
        current_year = datetime.now().year
        selected_year = request.GET.get('year', current_year)
        
        try:
            selected_year = int(selected_year)
        except (ValueError, TypeError):
            selected_year = current_year
        
        performances = Performance.objects.filter(
            event_date__year=selected_year
        ).select_related('city', 'event_type').order_by('event_date')
        
        context['performances'] = performances
        context['selected_year'] = selected_year
        context['current_language'] = current_language
        
        # Get available years for year selector
        available_years = Performance.objects.dates('event_date', 'year').values_list(
            'event_date__year', flat=True
        ).distinct().order_by('-event_date__year')
        context['available_years'] = list(available_years)

        event_types_data = {}
        for et in EventType.objects.all():
            event_types_data[et.name] = {
                'order': et.order,
                'name_en': et.name_en or et.name
            }
        context['event_types_data'] = json.dumps(event_types_data)

        cities_data = {}
        for city in City.objects.all():
            cities_data[city.name] = {
                'order': city.order,
                'name_en': city.name_en or city.name
            }
        context['cities_data'] = json.dumps(cities_data)

        if self.logo:
            logo_rendition = self.logo.get_rendition('width-200')
            context['logo_url'] = logo_rendition.url
        else:
            context['logo_url'] = None
        
        return context
    
    class Meta:
        verbose_name = "回顧頁面 / Replay Page"