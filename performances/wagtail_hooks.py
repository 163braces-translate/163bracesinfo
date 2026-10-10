from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet

from .models import Album, City, EventType, Performance, Song


# 後台 snippet 列表的搜尋：search_backend_name = None 改用資料庫 icontains 查詢，
# 中文可部分比對（例如搜「楊桃」找得到「阿源楊桃綠」），不需要建搜尋索引。
class SearchableSnippetViewSet(SnippetViewSet):
    search_backend_name = None


class EventTypeViewSet(SearchableSnippetViewSet):
    model = EventType
    search_fields = ["name", "name_en"]


class CityViewSet(SearchableSnippetViewSet):
    model = City
    search_fields = ["name", "name_en"]


class PerformanceViewSet(SearchableSnippetViewSet):
    model = Performance
    search_fields = [
        "event_name",
        "event_name_en",
        "venue",
        "venue_en",
        "city__name",
        "event_type__name",
    ]
    list_filter = ["event_type", "city"]


class AlbumViewSet(SearchableSnippetViewSet):
    model = Album
    search_fields = ["name", "name_en"]


class SongViewSet(SearchableSnippetViewSet):
    model = Song
    search_fields = ["title", "title_en", "artist", "artist_en", "album__name"]
    list_filter = ["album"]


register_snippet(EventTypeViewSet)
register_snippet(CityViewSet)
register_snippet(PerformanceViewSet)
register_snippet(AlbumViewSet)
register_snippet(SongViewSet)
