from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from analytics.pipeline import run_for_user
from cloud_accounts.models import CloudAccount

from .models import ImportJob
from .services import run_import


def validate_upload(uploaded, extensions):
    """Shared upload checks: extension and size limit."""
    name = uploaded.name.lower()
    if not name.endswith(tuple(extensions)):
        raise forms.ValidationError(f"Upload a {' or '.join(extensions)} file.")
    if uploaded.size > settings.MAX_UPLOAD_BYTES:
        limit_mb = settings.MAX_UPLOAD_BYTES // (1024 * 1024)
        raise forms.ValidationError(f"The file is larger than the {limit_mb} MB limit.")
    return uploaded


class BillingUploadForm(forms.Form):
    cloud_account = forms.ModelChoiceField(queryset=CloudAccount.objects.none())
    file = forms.FileField(label="Billing CSV export")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cloud_account"].queryset = CloudAccount.objects.filter(user=user)

    def clean_file(self):
        return validate_upload(self.cleaned_data["file"], [".csv"])


@login_required
def import_list(request):
    jobs = ImportJob.objects.filter(user=request.user).select_related("cloud_account")
    return render(request, "ingestion/list.html", {"jobs": jobs})


@login_required
def import_upload(request):
    form = BillingUploadForm(request.POST or None, request.FILES or None, user=request.user)
    has_accounts = CloudAccount.objects.filter(user=request.user).exists()
    if request.method == "POST" and form.is_valid():
        uploaded = form.cleaned_data["file"]
        job = ImportJob.objects.create(
            user=request.user,
            cloud_account=form.cleaned_data["cloud_account"],
            source_file=uploaded.name[:255],
        )
        run_import(job, uploaded)  # the file is parsed in memory and not stored
        if job.records_imported:
            run_for_user(request.user)
        if job.status == ImportJob.FAILED:
            messages.error(request, "The import failed. See the details below.")
        else:
            messages.success(request, f"Imported {job.records_imported} billing rows.")
        return redirect("import_detail", pk=job.pk)
    return render(
        request,
        "ingestion/upload.html",
        {"form": form, "has_accounts": has_accounts,
         "limit_mb": settings.MAX_UPLOAD_BYTES // (1024 * 1024)},
    )


@login_required
def import_detail(request, pk):
    job = get_object_or_404(ImportJob, pk=pk, user=request.user)
    return render(request, "ingestion/detail.html", {"job": job})
