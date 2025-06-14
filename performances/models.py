from django.db import models
from wagtail.snippets.models import register_snippet

from myproject.utils.models import BasePage
from wagtail.fields import RichTextField
from wagtail.admin.panels import FieldPanel

from django.db.models import Count, Q
from django.db.models.functions import Extract
import json
import calendar

@register_snippet
class EventType(models.Model):
    name = models.CharField("類型", max_length=50)
    order = models.PositiveIntegerField("排序順序", default=0)

    class Meta:
        ordering = ["order", "name"]  # 預設排序：先依 order，再依 name

    def __str__(self):
        return self.name

@register_snippet
class City(models.Model):
    name = models.CharField("城市", max_length=50)
    order = models.PositiveIntegerField("排序順序", default=0)

    class Meta:
        ordering = ["order", "name"]  # 預設排序：先依 order，再依 name

    def __str__(self):
        return self.name

@register_snippet
class Performance(models.Model):
    event_date = models.DateField("表演日期")
    event_name = models.CharField("表演名稱", max_length=255)
    event_type = models.ForeignKey(EventType, on_delete=models.PROTECT)
    venue = models.CharField("地點", max_length=255)
    city = city = models.ForeignKey(City, on_delete=models.PROTECT)

    def __str__(self):
        return f"{self.event_date} - {self.event_name}"


from .models import Performance, City, EventType

class PerformanceListPage(BasePage):
    template = "pages/performance_list_page.html"
    intro = RichTextField(blank=True)

    content_panels = BasePage.content_panels + [
        FieldPanel("intro"),
    ]

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)

        performances = Performance.objects.all()

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
        colors = ['#FF6384', '#36A2EB', '#9966FF', '#FF9F40']
        
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
                    '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', 
                    '#9966FF', '#FF9F40', '#FF6384', '#C9CBCF'
                ][:len(city_stats)]
            }]
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

        history_colors = ['#FF6384', '#36A2EB', '#9966FF', '#FF9F40']

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
            'total_performances': performances.count(),
            'city_stats': city_stats,
        })
        
        return context