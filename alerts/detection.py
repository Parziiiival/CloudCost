"""Cost anomaly detection.

For every (provider, service) the daily USD cost is compared with a rolling
baseline of the previous days. A day is flagged when it is far above that
baseline, by standard deviations or by percentage. Flags are statistical
signals for a person to review - never a statement of error, fraud or misuse.
"""
from decimal import Decimal

import numpy as np

from analytics.engine import load_frame, service_daily_series
from cloud_accounts.models import PROVIDER_LABELS

from .models import CostAnomaly

WINDOW_DAYS = 14
MIN_BASELINE_DAYS = 7
MIN_DEVIATION_USD = 5.0
Z_THRESHOLD = 3.0
Z_MIN_PCT = 25.0
PCT_THRESHOLD = 75.0


def detect_in_series(series):
    """Pure function over one zero-filled daily Series. Returns a list of dicts."""
    values = series.to_numpy(dtype=float)
    flagged = np.zeros(len(values), dtype=bool)
    found = []
    for i in range(MIN_BASELINE_DAYS, len(values)):
        # Earlier flagged days are left out so one spike does not hide the next.
        baseline = [values[j] for j in range(i) if not flagged[j]][-WINDOW_DAYS:]
        if len(baseline) < MIN_BASELINE_DAYS:
            continue
        mean = float(np.mean(baseline))
        std = float(np.std(baseline, ddof=1))
        observed = float(values[i])
        deviation = observed - mean
        if deviation < MIN_DEVIATION_USD:
            continue
        pct = deviation / mean * 100 if mean > 0 else None
        z = deviation / std if std > 0 else None
        if mean <= 0:
            method = "new_spend"
        elif z is not None and z >= Z_THRESHOLD and pct >= Z_MIN_PCT:
            method = "rolling_zscore"
        elif pct >= PCT_THRESHOLD:
            method = "pct_threshold"
        else:
            continue
        flagged[i] = True
        found.append(
            {
                "day": series.index[i].date(),
                "observed": observed,
                "expected": mean,
                "deviation": deviation,
                "pct": pct,
                "z": z,
                "std": std,
                "baseline_days": len(baseline),
                "method": method,
            }
        )
    return found


def _explain(provider, service, hit):
    label = PROVIDER_LABELS.get(provider, provider)
    parts = [
        f"{label} {service} cost on {hit['day']:%Y-%m-%d} was ${hit['observed']:,.2f}. "
        f"The average of the previous {hit['baseline_days']} normal days was "
        f"${hit['expected']:,.2f} (standard deviation ${hit['std']:,.2f})."
    ]
    if hit["method"] == "new_spend":
        parts.append(
            f"The service had no spend in the baseline period, so ${hit['deviation']:,.2f} of new "
            f"daily spend was flagged (minimum ${MIN_DEVIATION_USD:,.0f})."
        )
    elif hit["method"] == "rolling_zscore":
        parts.append(
            f"That is ${hit['deviation']:,.2f} ({hit['pct']:.1f}%) above the baseline and "
            f"{hit['z']:.1f} standard deviations from it. Rule: at least {Z_THRESHOLD:.0f} standard "
            f"deviations and {Z_MIN_PCT:.0f}% above the rolling average."
        )
    else:
        parts.append(
            f"That is ${hit['deviation']:,.2f} ({hit['pct']:.1f}%) above the baseline. "
            f"Rule: at least {PCT_THRESHOLD:.0f}% above the rolling average."
        )
    parts.append(
        "This is a statistical flag for review, not a determination of error or misuse. "
        "Planned launches, batch jobs or billing adjustments can cause the same pattern."
    )
    return " ".join(parts)


def _d(value, places="0.01"):
    return Decimal(str(value)).quantize(Decimal(places))


def detect_for_user(user):
    """Recompute anomalies for a user. Returns the number currently detected."""
    data = load_frame(user)
    keys = set()
    for (provider, service), series in service_daily_series(data).items():
        for hit in detect_in_series(series):
            keys.add((provider, service, hit["day"]))
            # update_or_create keeps the review status a person already set.
            CostAnomaly.objects.update_or_create(
                user=user,
                provider=provider,
                service=service,
                usage_date=hit["day"],
                defaults={
                    "observed_cost": _d(hit["observed"]),
                    "expected_cost": _d(hit["expected"]),
                    "deviation": _d(hit["deviation"]),
                    "deviation_pct": None if hit["pct"] is None else _d(min(hit["pct"], 9999999999.0), "0.1"),
                    "currency": "USD",
                    "method": hit["method"],
                    "explanation": _explain(provider, service, hit),
                },
            )
    # Open flags that the data no longer supports are withdrawn; reviewed ones stay.
    for anomaly in CostAnomaly.objects.filter(user=user, status="open"):
        if (anomaly.provider, anomaly.service, anomaly.usage_date) not in keys:
            anomaly.delete()
    return len(keys)
