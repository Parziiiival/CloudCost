import csv

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from alerts.models import CostAnomaly
from analytics import engine
from analytics.filtering import filters_from_request
from analytics.models import CostForecast
from cloud_accounts.models import PROVIDERS
from estimates.models import InfracostEstimate
from recommendations.models import Recommendation

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    """Neutralise spreadsheet formula injection in text cells."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def _csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(header)
    for row in rows:
        writer.writerow([safe_cell(cell) for cell in row])
    return response


@login_required
def index(request):
    filters = filters_from_request(request)
    return render(
        request,
        "reports/index.html",
        {"filters": filters, "providers": PROVIDERS, "options": engine.filter_options(request.user)},
    )


@login_required
def costs_csv(request):
    filters = filters_from_request(request)
    data = engine.load_frame(request.user, filters)
    rows = data.query(
        "SELECT strftime(CAST(day AS DATE), '%Y-%m-%d'), provider, service, region, project, "
        "ROUND(SUM(cost_usd), 4) FROM billing GROUP BY ALL ORDER BY 1, 2, 3, 4, 5"
    )
    return _csv_response(
        f"costs_{filters.start}_{filters.end}.csv",
        ["date", "provider", "service", "region", "project", "cost_usd"],
        rows,
    )


@login_required
def anomalies_csv(request):
    rows = [
        (a.usage_date.isoformat(), a.provider, a.service, f"{a.observed_cost:.2f}",
         f"{a.expected_cost:.2f}", f"{a.deviation:.2f}",
         "" if a.deviation_pct is None else f"{a.deviation_pct:.1f}",
         a.currency, a.method, a.status, a.explanation)
        for a in CostAnomaly.objects.filter(user=request.user)
    ]
    return _csv_response(
        "anomalies.csv",
        ["usage_date", "provider", "service", "observed_cost", "expected_cost", "deviation",
         "deviation_pct", "currency", "method", "status", "explanation"],
        rows,
    )


@login_required
def recommendations_csv(request):
    rows = [
        (r.category, r.title, "" if r.estimated_savings is None else f"{r.estimated_savings:.2f}",
         r.currency, r.status, r.review_note, r.explanation)
        for r in Recommendation.objects.filter(user=request.user)
    ]
    return _csv_response(
        "recommendations.csv",
        ["category", "title", "estimated_monthly_savings", "currency", "status", "review_note",
         "explanation"],
        rows,
    )


@login_required
def summary(request):
    user = request.user
    filters = filters_from_request(request)
    data = engine.load_frame(user, filters)
    total = engine.total(data)
    by_provider = engine.by_dimension(data, "provider")
    for row in by_provider:
        row["share"] = round(row["cost"] / total * 100, 1) if total > 0 else None
    context = {
        "filters": filters,
        "generated_at": timezone.now(),
        "total": total,
        "empty": data.empty,
        "comparison": engine.period_comparison(user, filters) if not data.empty else None,
        "by_provider": by_provider,
        "by_service": engine.by_dimension(data, "service", limit=10),
        "by_project": engine.by_dimension(data, "project", limit=10),
        "top_resources": engine.top_resources(data, 10),
        "anomalies": CostAnomaly.objects.filter(
            user=user, usage_date__gte=filters.start, usage_date__lte=filters.end
        ),
        "recommendations": Recommendation.objects.filter(user=user, status="open"),
        "forecast": CostForecast.objects.filter(user=user).first(),
        "estimates": InfracostEstimate.objects.filter(user=user),
        "unconverted": data.unconverted,
    }
    return render(request, "reports/summary.html", context)
