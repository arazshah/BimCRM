from django.urls import path

from . import views

app_name = "sites"

urlpatterns = [
    path("", views.home, name="home"),
    path("quote/", views.submit_quote, name="quote"),
    path("track/", views.track, name="track"),
    path("account/", views.account, name="account"),
    path("account/logout/", views.account_logout, name="account_logout"),
]
