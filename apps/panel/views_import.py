"""Excel import: download the standard template, upload, preview, confirm."""

import logging
import os
import uuid

from django import forms
from django.contrib import messages
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import DatabaseError
from django.http import HttpResponse
from django.shortcuts import redirect, render

from .access import panel_view
from .importer import MAX_BYTES, SHEETS, Importer, ImportFileError, build_template, read_rows

logger = logging.getLogger(__name__)

SESSION_KEY = "import_upload"


class UploadForm(forms.Form):
    file = forms.FileField(
        label="فایل اکسل",
        help_text="فایل .xlsx ساخته‌شده از قالب. فایل CSV هم پذیرفته می‌شود.",
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx,.csv"}),
    )

    def clean_file(self):
        f = self.cleaned_data["file"]
        if f.size > MAX_BYTES:
            raise forms.ValidationError("حجم فایل بیش از ۱۰ مگابایت است؛ آن را در چند فایل جدا وارد کنید.")
        return f


def _importer(request):
    return Importer(
        request.tenant,
        user=request.user,
        branch=request.branch_scope,
        features=request.features,
        can_finance=request.membership.can("finance"),
    )


def _forget(request):
    info = request.session.pop(SESSION_KEY, None)
    if info:
        try:
            default_storage.delete(info["path"])
        except OSError:
            pass


def _sheets(request):
    finance = "finance" in request.features and request.membership.can("finance")
    return [s for s in SHEETS if finance or not s.feature]


@panel_view()
def data_import(request):
    ctx = {"sheets": _sheets(request), "form": UploadForm()}
    if request.method != "POST":
        return render(request, "panel/import.html", ctx)

    action = request.POST.get("action", "preview")
    if action == "cancel":
        _forget(request)
        messages.info(request, "ورود لغو شد و چیزی ثبت نشد.")
        return redirect("panel:data_import")

    if action == "confirm":
        info = request.session.get(SESSION_KEY)
        if not info or info.get("tenant") != request.tenant.pk or not default_storage.exists(info["path"]):
            messages.error(request, "فایل پیش‌نمایش پیدا نشد؛ لطفاً دوباره بارگذاری کنید.")
            return redirect("panel:data_import")
        with default_storage.open(info["path"], "rb") as fh:
            data = fh.read()
        try:
            report = _importer(request).run(read_rows(info["name"], data), commit=True)
        except ImportFileError as exc:
            _forget(request)
            messages.error(request, str(exc))
            return redirect("panel:data_import")
        except DatabaseError:
            logger.exception("excel import failed for tenant %s", request.tenant.pk)
            messages.error(
                request, "ثبت انجام نشد و هیچ تغییری ذخیره نشد. لطفاً فایل را بررسی کنید یا با پشتیبانی تماس بگیرید."
            )
            return redirect("panel:data_import")
        _forget(request)
        messages.success(request, f"ورود انجام شد: {report.changes:,} مورد ثبت یا به‌روز شد.")
        return render(request, "panel/import.html", {**ctx, "report": report, "done": True, "filename": info["name"]})

    form = UploadForm(request.POST, request.FILES)
    ctx["form"] = form
    if not form.is_valid():
        return render(request, "panel/import.html", ctx)
    upload = form.cleaned_data["file"]
    data = upload.read()
    try:
        report = _importer(request).run(read_rows(upload.name, data), commit=False)
    except ImportFileError as exc:
        form.add_error("file", str(exc))
        return render(request, "panel/import.html", ctx)
    _forget(request)
    ext = os.path.splitext(upload.name)[1].lower()[:6] or ".xlsx"
    path = default_storage.save(f"imports/{request.tenant.pk}/{uuid.uuid4().hex}{ext}", ContentFile(data))
    request.session[SESSION_KEY] = {"path": path, "name": upload.name, "tenant": request.tenant.pk}
    return render(request, "panel/import.html", {**ctx, "report": report, "preview": True, "filename": upload.name})


@panel_view()
def import_template(request):
    finance = "finance" in request.features and request.membership.can("finance")
    resp = HttpResponse(
        build_template(include_finance=finance),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = 'attachment; filename="bimcrm-import-template.xlsx"'
    return resp
