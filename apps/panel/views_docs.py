"""Customer documents in the panel."""

from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.crm.documents import validate_upload
from apps.crm.models import Customer, CustomerDocument

from .access import panel_view, scoped, storage_used_bytes


class DocumentForm(forms.ModelForm):
    class Meta:
        model = CustomerDocument
        fields = ["kind", "title", "policy", "file"]

    def __init__(self, *args, customer=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["policy"].queryset = (
            customer.policies.select_related("line") if customer else CustomerDocument.objects.none()
        )
        self.fields["policy"].required = False
        self.fields["policy"].empty_label = "مربوط به بیمه‌نامه خاصی نیست"
        self.fields["title"].required = False

    def clean_file(self):
        f = self.cleaned_data["file"]
        err = validate_upload(f)
        if err:
            raise forms.ValidationError(err)
        return f


@panel_view()
@require_POST
def document_upload(request, pk):
    customer = get_object_or_404(scoped(request, Customer.objects.all()), pk=pk)
    form = DocumentForm(request.POST, request.FILES, customer=customer)
    back = reverse("panel:customer", args=[customer.pk]) + "#docs"
    nxt = request.POST.get("next", "")
    if nxt.startswith("/panel/"):
        back = nxt
    if not form.is_valid():
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
        return redirect(back)
    sub = request.subscription
    f = form.cleaned_data["file"]
    if sub and f.size > sub.storage_limit_bytes() - storage_used_bytes(request.tenant):
        messages.error(request, "فضای محیط پر است. از بخش اشتراک فضا اضافه کنید.")
        return redirect(back)
    doc = form.save(commit=False)
    doc.customer, doc.uploaded_by = customer, request.user
    doc.save()
    messages.success(request, f"{doc.get_kind_display()} در پرونده {customer.full_name} ذخیره شد.")
    return redirect(back)


@panel_view()
@require_POST
def document_delete(request, pk, doc_id):
    customer = get_object_or_404(scoped(request, Customer.objects.all()), pk=pk)
    doc = get_object_or_404(CustomerDocument, pk=doc_id, customer=customer)
    doc.file.delete(save=False)
    doc.delete()
    messages.success(request, "مدرک حذف شد.")
    return redirect(reverse("panel:customer", args=[customer.pk]) + "#docs")
