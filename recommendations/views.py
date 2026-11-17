from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import ai
from .models import Recommendation

STATUSES = [value for value, _ in Recommendation.STATUS]


@login_required
def recommendation_list(request):
    status = request.GET.get("status", "")
    if status not in STATUSES:
        status = ""
    recs = Recommendation.objects.filter(user=request.user)
    open_savings = recs.filter(status="open").aggregate(s=Sum("estimated_savings"))["s"]
    total = recs.count()
    if status:
        recs = recs.filter(status=status)
    return render(
        request,
        "recommendations/list.html",
        {
            "recommendations": recs,
            "status": status,
            "statuses": Recommendation.STATUS,
            "open_savings": open_savings,
            "total": total,
            "ai_enabled": ai.is_enabled(),
        },
    )


@login_required
@require_POST
def recommendation_status(request, pk):
    rec = get_object_or_404(Recommendation, pk=pk, user=request.user)
    status = request.POST.get("status", "")
    if status not in STATUSES:
        messages.error(request, "Unknown status.")
        return redirect("recommendations")
    rec.status = status
    rec.review_note = request.POST.get("review_note", "").strip()[:300]
    rec.save(update_fields=["status", "review_note", "updated_at"])
    messages.success(request, f"Recommendation marked {rec.get_status_display().lower()}.")
    return redirect("recommendations")


@login_required
@require_POST
def recommendation_explain(request, pk):
    rec = get_object_or_404(Recommendation, pk=pk, user=request.user)
    try:
        rec.ai_explanation = ai.explain(rec)
    except ai.AIError as exc:
        messages.error(request, f"No AI explanation was added: {exc}")
    else:
        rec.save(update_fields=["ai_explanation", "updated_at"])
        messages.success(request, "AI explanation added. Figures come from the evidence, not the model.")
    return redirect("recommendations")
