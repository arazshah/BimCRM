from django.urls import path

from . import views

app_name = "sites"

urlpatterns = [
    path("", views.home, name="home"),
    path("quote/", views.submit_quote, name="quote"),
    path("quote/done/", views.quote_done, name="quote_done"),
    path("track/", views.track, name="track"),
    path("insurance/<slug:slug>/", views.line_detail, name="line_detail"),
    path("guide/<str:kind>/", views.guide, name="guide"),
    path("privacy/", views.privacy, name="privacy"),
    path("robots.txt", views.robots),
    path("sitemap.xml", views.sitemap),
    path("favicon.ico", views.favicon),
    path("account/", views.account, name="account"),
    path("account/logout/", views.account_logout, name="account_logout"),
    path("account/documents/", views.account_document_upload, name="account_document_upload"),
    path("account/claims/report/", views.account_claim_report, name="account_claim_report"),
    path("account/claims/<int:claim_id>/upload/", views.account_claim_upload, name="account_claim_upload"),
]
