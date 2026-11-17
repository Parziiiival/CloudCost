from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme


def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("dashboard")
    return render(request, "accounts/signup.html", {"form": form})


def _safe_next(request):
    target = request.GET.get("next", "")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return ""


def csrf_failure(request, reason=""):
    """Handle a rejected form post. The post itself is never processed.

    The usual cause is a stale token: signing in rotates the CSRF token, so a
    second submit of the same sign-in form (double click, or a page left open
    in another tab) no longer matches. Send the browser to a fresh page.
    """
    user = getattr(request, "user", None)
    auth_paths = (reverse("login"), reverse("signup"))
    if user is not None and user.is_authenticated:
        if request.path in auth_paths:
            # Already signed in by the first submit: carry on to the app.
            return redirect(_safe_next(request) or "dashboard")
        messages.error(request, "That form had expired, so nothing was changed. Please try again.")
        referer = request.META.get("HTTP_REFERER", "")
        if referer and url_has_allowed_host_and_scheme(
            referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            return redirect(referer)
        return redirect("dashboard")
    messages.error(request, "Your session expired. Please sign in again.")
    target = _safe_next(request)
    url = reverse("signup") if request.path == reverse("signup") else reverse("login")
    if target:
        url = f"{url}?{urlencode({'next': target})}"
    return redirect(url)
