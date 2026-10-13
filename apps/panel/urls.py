from django.urls import path

from . import views
from . import views_addons as addons

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
    path("branches/", views.branches, name="branches"),
    path("branches/new/", views.branch_edit, name="branch_new"),
    path("branches/<int:pk>/edit/", views.branch_edit, name="branch_edit"),
    path("billing/", views.billing, name="billing"),
    path("billing/pay/", views.billing_pay, name="billing_pay"),
    path("support/", views.tickets, name="tickets"),
    path("support/<int:pk>/", views.ticket_detail, name="ticket"),
    # Reminders (base package)
    path("reminders/", addons.reminders, name="reminders"),
    # Finance add-on
    path("finance/", addons.finance, name="finance"),
    path("finance/installments/", addons.installments, name="installments"),
    path("finance/installments/plan/", addons.installment_plan, name="installment_plan"),
    path("finance/installments/<int:pk>/", addons.installment_edit, name="installment_edit"),
    path("finance/installments/<int:pk>/paid/", addons.installment_paid, name="installment_paid"),
    path("finance/commissions/", addons.commissions, name="commissions"),
    path("finance/commissions/rules/<int:pk>/delete/", addons.commission_rule_delete, name="commission_rule_delete"),
    path("finance/commissions/<int:pk>/receive/", addons.commission_receive, name="commission_receive"),
    path("finance/ledger/", addons.ledger, name="ledger"),
    path("finance/ledger/<int:pk>/delete/", addons.ledger_delete, name="ledger_delete"),
    # Claims add-on
    path("claims/", addons.claims, name="claims"),
    path("claims/new/", addons.claim_new, name="claim_new"),
    path("claims/<int:pk>/", addons.claim_detail, name="claim"),
    path("claims/<int:pk>/edit/", addons.claim_edit, name="claim_edit"),
    # Marketers add-on
    path("marketers/", addons.marketers, name="marketers"),
    path("marketers/new/", addons.marketer_edit, name="marketer_new"),
    path("marketers/<int:pk>/", addons.marketer_detail, name="marketer"),
    path("marketers/<int:pk>/edit/", addons.marketer_edit, name="marketer_edit"),
    # SMS campaigns add-on
    path("campaigns/", addons.campaigns, name="campaigns"),
    path("campaigns/<int:pk>/", addons.campaign_detail, name="campaign"),
    # Advanced reports add-on
    path("reports/", addons.reports, name="reports"),
    path("reports/policies.csv", addons.reports_export, name="reports_export"),
]
