from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import CostAnomaly

STATUSES = [value for value, _ in CostAnomaly.STATUS]


@login_required
def anomaly_list(request):
    status = request.GET.get("status", "")
    if status not in STATUSES:
        status = ""
    anomalies = CostAnomaly.objects.filter(user=request.user)
    total = anomalies.count()
    if status:
        anomalies = anomalies.filter(status=status)
    return render(
        request,
        "alerts/list.html",
        {"anomalies": anomalies, "status": status, "statuses": CostAnomaly.STATUS, "total": total},
    )


@login_required
@require_POST
def anomaly_status(request, pk):
    anomaly = get_object_or_404(CostAnomaly, pk=pk, user=request.user)
    status = request.POST.get("status", "")
    if status in STATUSES:
        anomaly.status = status
        anomaly.save(update_fields=["status"])
        messages.success(request, f"Anomaly marked {anomaly.get_status_display().lower()}.")
    else:
        messages.error(request, "Unknown status.")
    return redirect("anomalies")
