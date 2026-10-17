from django.urls import include, path, re_path

from apps.core.media import serve_media
from apps.core.views import tls_ask

urlpatterns = [
    path("internal/tls-ask", tls_ask),
    re_path(r"^media/(?P<path>(?:logos|companies|showcases)/.+)$", serve_media),
    path("", include("apps.main.urls")),
]
