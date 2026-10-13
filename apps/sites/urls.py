from django.urls import path

from . import views

app_name = "sites"

urlpatterns = [
    path("", views.home, name="home"),
    path("quote/", views.submit_quote, name="quote"),
    path("track/", views.track, name="track"),
    path("account/", views.account, name="account"),
    path("account/logout/", views.account_logout, name="account_logout"),
    path("account/claims/report/", views.account_claim_report, name="account_claim_report"),
    path("account/claims/<int:claim_id>/upload/", views.account_claim_upload, name="account_claim_upload"),
]
