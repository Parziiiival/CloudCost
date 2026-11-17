from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from analytics import engine
from analytics.pipeline import run_for_user
from ingestion.views import validate_upload

from .importer import import_inventory
from .models import CloudResource


class InventoryUploadForm(forms.Form):
    file = forms.FileField(label="CloudQuery inventory export (JSON)")

    def clean_file(self):
        return validate_upload(self.cleaned_data["file"], [".json", ".jsonl"])


@login_required
def resource_list(request):
    user = request.user
    start, end = engine.default_range(user)
    data = engine.load_frame(user, engine.Filters(start=start, end=end))
    costs = dict(
        data.query("SELECT resource_id, SUM(cost_usd) FROM billing WHERE resource_id <> '' GROUP BY 1")
    )
    resources = list(CloudResource.objects.filter(user=user))
    for resource in resources:
        resource.cost_30d = costs.get(resource.resource_id)
    return render(
        request,
        "resources/list.html",
        {"resources": resources, "start": start, "end": end},
    )


@login_required
def resource_import(request):
    form = InventoryUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            text = form.cleaned_data["file"].read().decode("utf-8-sig")
            imported, skipped = import_inventory(request.user, text)
        except UnicodeDecodeError:
            form.add_error("file", "The file is not UTF-8 encoded text.")
        except ValueError as exc:
            form.add_error("file", str(exc))
        else:
            run_for_user(request.user)
            messages.success(
                request, f"Inventory updated: {imported} resources imported, {skipped} skipped."
            )
            return redirect("resources")
    return render(request, "resources/import.html", {"form": form})
