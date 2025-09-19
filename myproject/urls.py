from django.conf import settings
from django.urls import include, path, re_path
from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.http import HttpResponse

from wagtail.admin import urls as wagtailadmin_urls
from wagtail import urls as wagtail_urls
from wagtail.documents import urls as wagtaildocs_urls

from myproject.search import views as search_views
from wagtail.contrib.sitemaps.views import sitemap
from wagtail.contrib.sitemaps.views import sitemap as wagtail_sitemap

def sitemap(request):
    response = wagtail_sitemap(request)
    # 強制移除或覆蓋 X-Robots-Tag
    response['X-Robots-Tag'] = 'index, follow'
    return response


def robots_txt(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        "",
        "# Sitemap",
        "Sitemap: https://163braces.info/sitemap.xml",
        "",
        
        "Disallow: /admin/",
        "Disallow: /cms/",
        "Disallow: /django-admin/",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("admin/", include(wagtailadmin_urls)),
    path("documents/", include(wagtaildocs_urls)),
    path("search/", search_views.search, name="search"),
    path('sitemap.xml', sitemap),
    path('robots.txt', robots_txt),
]


#if settings.DEBUG:
from django.conf.urls.static import static
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
#新的
from django.views.static import serve

# Serve static and media files from development server
#urlpatterns += staticfiles_urlpatterns()
#urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

#新的解方
# 手動添加 media 文件服務（繞過 DEBUG 檢查）
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {
        'document_root': settings.MEDIA_ROOT,
    }),
]

# 添加 static 文件服務
urlpatterns += staticfiles_urlpatterns()


# Add language-prefixed URL patterns
urlpatterns += i18n_patterns(
    path("", include(wagtail_urls)),
    prefix_default_language=False  # Don't add /zh-hant/ prefix for Chinese
)


