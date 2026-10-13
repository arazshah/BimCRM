from django.contrib import admin
from django.urls import path, re_path
from django.views.generic import RedirectView

from apps.core.media import serve_media

urlpatterns = [
    path("", RedirectView.as_view(url="/admin/", permanent=False)),
    path("admin/", admin.site.urls),
    re_path(r"^media/(?P<path>.+)$", serve_media),
]
