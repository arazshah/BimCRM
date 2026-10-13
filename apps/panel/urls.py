from django.urls import path

from . import views

app_name = "panel"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("customers/", views.customers, name="customers"),
    path("customers/new/", views.customer_edit, name="customer_new"),
    path("customers/import/", views.customer_import, name="customer_import"),
    path("customers/<int:pk>/", views.customer_detail, name="customer"),
    path("customers/<int:pk>/edit/", views.customer_edit, name="customer_edit"),
    path("policies/", views.policies, name="policies"),
    path("policies/new/", views.policy_edit, name="policy_new"),
    path("policies/<int:pk>/edit/", views.policy_edit, name="policy_edit"),
    path("quotes/", views.quotes, name="quotes"),
    path("quotes/<int:pk>/", views.quote_detail, name="quote"),
    path("site/", views.site_settings, name="site"),
    path("site/template/", views.site_template, name="site_template"),
    path("site/publish/", views.site_publish, name="site_publish"),
    path("domains/", views.domains, name="domains"),
    path("domains/<int:pk>/", views.domain_action, name="domain_action"),
    path("integrations/", views.integrations, name="integrations"),
    path("integrations/<str:kind>/<str:provider>/", views.integration_edit, name="integration_edit"),
    path("team/", views.team, name="team"),
    path("team/<int:pk>/remove/", views.team_remove, name="team_remove"),
    path("billing/", views.billing, name="billing"),
    path("support/", views.tickets, name="tickets"),
    path("support/<int:pk>/", views.ticket_detail, name="ticket"),
]
