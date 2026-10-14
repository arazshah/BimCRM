from django.templatetags.static import static
from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "main"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("templates/<str:key>/", views.template_preview, name="template_preview"),
    path("api/check-slug/", views.check_slug, name="check_slug"),
    path("login/", views.login_start, name="login"),
    path("login/verify/", views.login_verify, name="login_verify"),
    path("logout/", views.logout_view, name="logout"),
    path("me/", views.dashboard, name="dashboard"),
    path("signup/", views.signup, name="signup"),
    path("signup/template/", views.signup_template, name="signup_template"),
    path("signup/plan/", views.signup_plan, name="signup_plan"),
    path("pay/<str:tenant_slug>/", views.pay, name="pay"),
    path("pay/callback/<int:invoice_id>/", views.pay_callback, name="pay_callback"),
    path("help/", views.help_index, name="help"),
    path("help/videos/", views.help_videos, name="help_videos"),
    path("help/<slug:slug>/", views.help_article, name="help_article"),
    path("robots.txt", views.robots),
    path("sitemap.xml", views.sitemap, name="sitemap"),
    path("favicon.ico", RedirectView.as_view(url=static("img/favicon.ico"), permanent=True)),
    path("<str:name>.txt", views.verification_file, name="verification_file"),
    path("healthz", views.health, name="health"),
]
