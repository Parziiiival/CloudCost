from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from ingestion.views import validate_upload

from .models import InfracostEstimate
from .parser import parse_infracost


class EstimateUploadForm(forms.Form):
    name = forms.CharField(max_length=120, label="Estimate name")
    file = forms.FileField(
        label="Infracost JSON",
        help_text="Output of: infracost breakdown --path . --format json",
    )

    def clean_file(self):
        return validate_upload(self.cleaned_data["file"], [".json"])


@login_required
def estimate_list(request):
    estimates = InfracostEstimate.objects.filter(user=request.user)
    return render(request, "estimates/list.html", {"estimates": estimates})


@login_required
def estimate_upload(request):
    form = EstimateUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        uploaded = form.cleaned_data["file"]
        try:
            parsed = parse_infracost(uploaded.read().decode("utf-8-sig"))
        except UnicodeDecodeError:
            form.add_error("file", "The file is not UTF-8 encoded text.")
        except ValueError as exc:
            form.add_error("file", str(exc))
        else:
            estimate = InfracostEstimate.objects.create(
                user=request.user,
                name=form.cleaned_data["name"],
                source_file=uploaded.name[:255],
                total_monthly_cost=parsed["total"],
                currency=parsed["currency"],
                breakdown=parsed["breakdown"],
            )
            messages.success(request, "Estimate stored.")
            return redirect("estimate_detail", pk=estimate.pk)
    return render(request, "estimates/upload.html", {"form": form})


@login_required
def estimate_detail(request, pk):
    estimate = get_object_or_404(InfracostEstimate, pk=pk, user=request.user)
    return render(request, "estimates/detail.html", {"estimate": estimate})
