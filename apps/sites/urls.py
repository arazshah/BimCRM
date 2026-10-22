from django.urls import path

from . import claims_views, views

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
    path("manifest.webmanifest", views.web_manifest),
    path("sw.js", views.service_worker),
    path("pwa-icon.svg", views.pwa_icon),
    path("contact.vcf", views.office_vcard),
    path("offline/", views.offline, name="offline"),
    path("account/", views.account, name="account"),
    path("account/logout/", views.account_logout, name="account_logout"),
    path("account/documents/", views.account_document_upload, name="account_document_upload"),
    path("claims/", claims_views.claims_home, name="claims"),
    path("claims/new/", claims_views.claim_new, name="claim_new"),
    path("claims/mine/", claims_views.claims_mine, name="claims_mine"),
    path("claims/<int:pk>/", claims_views.claim_detail, name="claim_detail"),
    path("claims/<int:pk>/upload/", claims_views.claim_upload, name="claim_upload"),
    path("claims/<int:pk>/message/", claims_views.claim_message, name="claim_message"),
    path("claims/<int:pk>/sign/", claims_views.claim_sign, name="claim_sign"),
    path("claims/<int:pk>/file/<int:doc_id>/", claims_views.claim_file, name="claim_file"),
    path("account/claims/report/", views.account_claim_report, name="account_claim_report"),
    path("account/claims/<int:claim_id>/upload/", views.account_claim_upload, name="account_claim_upload"),
]
