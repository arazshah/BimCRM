from django import forms
from django.contrib.auth import get_user_model

from apps.accounts.models import Membership
from apps.crm.models import Customer
from apps.work.models import Activity, Task

from .forms import JalaliDateInput


def member_users(tenant):
    ids = Membership.objects.filter(tenant=tenant, is_active=True).values_list("user_id", flat=True)
    return get_user_model().objects.filter(pk__in=ids).order_by("full_name")


class UserChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.full_name or obj.mobile


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ["title", "kind", "customer", "assigned_to", "due_date", "due_time", "priority", "note"]
        widgets = {
            "due_date": JalaliDateInput(),
            "due_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, tenant=None, customers=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"] = UserChoice(
            queryset=member_users(tenant), required=False, label="مسئول", empty_label="هر کدام از همکاران"
        )
        self.fields["customer"].queryset = customers if customers is not None else Customer.objects.none()
        self.fields["customer"].required = False


class ActivityForm(forms.ModelForm):
    notify = UserChoice(queryset=None, required=False, label="اطلاع به همکار", empty_label="—")
    follow_up = forms.DateField(label="کار پیگیری برای تاریخ", required=False, widget=JalaliDateInput())
    follow_title = forms.CharField(label="عنوان کار پیگیری", required=False, max_length=160)

    class Meta:
        model = Activity
        fields = ["kind", "body"]
        widgets = {
            "body": forms.Textarea(
                attrs={"rows": 3, "placeholder": "مثلاً: تماس گرفتم، قیمت بدنه را خواست؛ پنجشنبه دوباره زنگ بزنم."}
            )
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["notify"].queryset = member_users(tenant)


class CustomerSmsForm(forms.Form):
    text = forms.CharField(label="متن پیامک", max_length=600, widget=forms.Textarea(attrs={"rows": 3}))
