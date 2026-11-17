from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import redirect, render

from .models import CloudAccount


class CloudAccountForm(forms.ModelForm):
    class Meta:
        model = CloudAccount
        fields = ["provider", "account_name", "account_identifier"]
        help_texts = {
            "account_identifier": "An account, subscription or billing account ID. "
            "Used only as a label - never enter keys or passwords here.",
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean(self):
        cleaned = super().clean()
        provider, identifier = cleaned.get("provider"), cleaned.get("account_identifier")
        if provider and identifier and CloudAccount.objects.filter(
            user=self.user, provider=provider, account_identifier=identifier
        ).exists():
            raise forms.ValidationError("You already have this account for that provider.")
        return cleaned


@login_required
def account_list(request):
    accounts = (
        CloudAccount.objects.filter(user=request.user)
        .annotate(record_count=Count("billing_records", distinct=True))
    )
    return render(request, "cloud_accounts/list.html", {"accounts": accounts})


@login_required
def account_add(request):
    form = CloudAccountForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        account = form.save(commit=False)
        account.user = request.user
        account.save()
        messages.success(request, f"Added {account}.")
        return redirect("cloud_accounts")
    return render(request, "cloud_accounts/add.html", {"form": form})
