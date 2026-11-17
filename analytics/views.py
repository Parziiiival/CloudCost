from dataclasses import replace

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from alerts.models import CostAnomaly
from billing.models import BillingRecord
from cloud_accounts.models import PROVIDER_LABELS, PROVIDERS
from recommendations.models import Recommendation

from . import engine
from .filtering import filters_from_request
from .forecasting import MODEL_LABELS, build_forecast
from .models import CostForecast
from .pipeline import run_for_user


@login_required
def dashboard(request):
    user = request.user
    filters = filters_from_request(request)
    has_data = BillingRecord.objects.filter(user=user).exists()
    data = engine.load_frame(user, filters)
    total = engine.total(data)

    daily = engine.daily_by_provider(data, filters.start, filters.end)
    providers_present = [p for p in PROVIDER_LABELS if p in daily["series"]]
    daily_rows = []
    for i, label in enumerate(daily["labels"]):
        values = [daily["series"][p][i] for p in providers_present]
        daily_rows.append({"date": label, "values": values, "total": round(sum(values), 2)})

    by_provider = engine.by_dimension(data, "provider")
    for row in by_provider:
        row["share"] = round(row["cost"] / total * 100, 1) if total > 0 else None

    all_time = engine.load_frame(user, replace(filters, start=None, end=None))
    charts = {
        "daily": daily,
        "monthly": engine.monthly_by_provider(all_time),
        "providers": by_provider,
        "services": engine.by_dimension(data, "service", limit=8),
        "regions": engine.by_dimension(data, "region", limit=8),
        "projects": engine.by_dimension(data, "project", limit=8),
    }
    open_recs = Recommendation.objects.filter(user=user, status="open")
    context = {
        "filters": filters,
        "providers": PROVIDERS,
        "options": engine.filter_options(user),
        "has_data": has_data,
        "period_empty": data.empty,
        "total": total,
        "comparison": engine.period_comparison(user, filters) if has_data else None,
        "forecast": CostForecast.objects.filter(user=user).first(),
        "open_anomalies": CostAnomaly.objects.filter(user=user, status="open").count(),
        "open_recommendations": open_recs.count(),
        "potential_savings": open_recs.aggregate(s=Sum("estimated_savings"))["s"],
        "charts": charts,
        "by_provider": by_provider,
        "top_resources": engine.top_resources(data, 10),
        "daily_rows": daily_rows,
        "daily_providers": [PROVIDER_LABELS[p] for p in providers_present],
        "unconverted": data.unconverted,
        "query": request.GET.urlencode(),
    }
    return render(request, "analytics/dashboard.html", context)


@login_required
def forecast(request):
    user = request.user
    data = engine.load_frame(user)
    history = engine.daily_totals(data)
    stored = CostForecast.objects.filter(user=user).first()
    if data.empty:
        result = {"status": "no_data"}
    elif stored:
        result = {
            "status": "ok",
            "history_days": stored.history_days,
            "model_name": stored.model_name,
            "model_label": MODEL_LABELS.get(stored.model_name, stored.model_name),
            "backtest_mae": stored.backtest_mae,
            "predicted": stored.predicted_cost,
            "lower": stored.lower_bound,
            "upper": stored.upper_bound,
            "period": stored.forecast_period,
            "daily": stored.daily,
            "notes": [n for n in stored.notes.split("\n") if n.strip()],
            "created_at": stored.created_at,
        }
    else:
        result = build_forecast(history)

    recent = history.tail(60)
    payload = {
        "history": {
            "labels": [d.strftime("%Y-%m-%d") for d in recent.index],
            "values": [round(float(v), 2) for v in recent.values],
        },
        "forecast": result.get("daily", []),
    }
    return render(
        request,
        "analytics/forecast.html",
        {"result": result, "payload": payload, "unconverted": data.unconverted},
    )


@login_required
@require_POST
def pipeline_run(request):
    result = run_for_user(request.user)
    forecast_status = result["forecast"]["status"].replace("_", " ")
    messages.success(
        request,
        f"Analysis refreshed: {result['anomalies']} anomalies flagged, "
        f"forecast {forecast_status}, {result['recommendations']} recommendations.",
    )
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return redirect(target)
    return redirect("dashboard")
