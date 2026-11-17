"""Turn dashboard/report query strings into validated Filters."""
from datetime import date

from cloud_accounts.models import PROVIDER_LABELS

from .engine import Filters, default_range


def _parse_date(value):
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def filters_from_request(request):
    params = request.GET
    provider = params.get("provider", "")
    if provider not in PROVIDER_LABELS:
        provider = ""
    start, end = _parse_date(params.get("start")), _parse_date(params.get("end"))
    if not start or not end or start > end:
        start, end = default_range(request.user)
    return Filters(
        provider=provider,
        service=params.get("service", "").strip()[:200],
        project=params.get("project", "").strip()[:200],
        start=start,
        end=end,
    )
