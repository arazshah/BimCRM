from django.urls import include, path, re_path

from apps.core.media import serve_media

urlpatterns = [
    path("panel/", include("apps.panel.urls")),
    re_path(r"^media/(?P<path>.+)$", serve_media),
    path("", include("apps.sites.urls")),
]
