"""Analytics engine.

Loads one user's normalized billing records into a Pandas DataFrame (costs
converted to USD with the ExchangeRate table) and answers aggregate questions
with DuckDB SQL. Every monetary figure shown in the app is computed here or in
the modules that build on it - never by an AI model.
"""
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone as dt_tz

import duckdb
import pandas as pd
from django.db.models import Max

from billing.models import BillingRecord, ExchangeRate

COLUMNS = ["provider", "service", "region", "project", "resource_id", "day", "cost_usd"]
DIMENSIONS = {"provider", "service", "region", "project", "resource_id"}
UNASSIGNED = "(unassigned)"


@dataclass(frozen=True)
class Filters:
    provider: str = ""
    service: str = ""
    project: str = ""
    start: date | None = None
    end: date | None = None


class CostData:
    """A user's billing rows in USD plus what could not be converted."""

    def __init__(self, df, unconverted):
        self.df = df
        self.unconverted = unconverted  # {currency: row count} left out of all totals

    @property
    def empty(self):
        return self.df.empty

    def query(self, sql, params=None):
        if self.df.empty:
            return []
        con = duckdb.connect()
        try:
            con.register("billing", self.df)
            return con.execute(sql, params or []).fetchall()
        finally:
            con.close()


def _day_start(day):
    return datetime.combine(day, time.min, tzinfo=dt_tz.utc)


def load_frame(user, filters=None):
    filters = filters or Filters()
    qs = BillingRecord.objects.filter(user=user)
    if filters.provider:
        qs = qs.filter(provider=filters.provider)
    if filters.service:
        qs = qs.filter(service=filters.service)
    if filters.project:
        qs = qs.filter(project_or_subscription=filters.project)
    if filters.start:
        qs = qs.filter(usage_start__gte=_day_start(filters.start))
    if filters.end:
        qs = qs.filter(usage_start__lt=_day_start(filters.end + timedelta(days=1)))

    rates = dict(ExchangeRate.objects.values_list("currency", "rate_to_usd"))
    rows, unconverted = [], {}
    fields = (
        "provider", "service", "region", "project_or_subscription",
        "resource_id", "usage_start", "cost", "currency",
    )
    for provider, service, region, project, resource_id, start, cost, currency in (
        qs.values_list(*fields).iterator()
    ):
        rate = rates.get(currency)
        if rate is None:
            # Never add up money in different currencies without a rate.
            unconverted[currency] = unconverted.get(currency, 0) + 1
            continue
        day = start.astimezone(dt_tz.utc).date()
        rows.append((provider, service, region, project, resource_id, day, float(cost * rate)))
    df = pd.DataFrame(rows, columns=COLUMNS)
    df["day"] = pd.to_datetime(df["day"])
    return CostData(df, unconverted)


def total(data):
    rows = data.query("SELECT COALESCE(SUM(cost_usd), 0) FROM billing")
    return float(rows[0][0]) if rows else 0.0


def by_dimension(data, dimension, limit=None):
    if dimension not in DIMENSIONS:
        raise ValueError(f"unknown dimension {dimension}")
    sql = (
        f"SELECT COALESCE(NULLIF({dimension}, ''), '{UNASSIGNED}') AS label, "
        "SUM(cost_usd) AS cost FROM billing GROUP BY 1 ORDER BY cost DESC, label"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [{"label": label, "cost": round(float(cost), 2)} for label, cost in data.query(sql)]


def top_resources(data, limit=10):
    rows = data.query(
        "SELECT resource_id, MIN(provider), MIN(service), SUM(cost_usd) AS cost "
        "FROM billing WHERE resource_id <> '' GROUP BY resource_id "
        f"ORDER BY cost DESC LIMIT {int(limit)}"
    )
    return [
        {"resource_id": rid, "provider": provider, "service": service, "cost": round(float(cost), 2)}
        for rid, provider, service, cost in rows
    ]


def daily_by_provider(data, start=None, end=None):
    """Zero-filled daily cost per provider: {"labels": [...], "series": {provider: [...]}}."""
    if data.empty:
        return {"labels": [], "series": {}}
    pivot = data.df.pivot_table(
        index="day", columns="provider", values="cost_usd", aggfunc="sum", fill_value=0.0
    )
    index = pd.date_range(start or pivot.index.min(), end or pivot.index.max(), freq="D")
    pivot = pivot.reindex(index, fill_value=0.0)
    return {
        "labels": [d.strftime("%Y-%m-%d") for d in pivot.index],
        "series": {str(col): [round(float(v), 2) for v in pivot[col]] for col in pivot.columns},
    }


def monthly_by_provider(data):
    rows = data.query(
        "SELECT strftime(CAST(day AS DATE), '%Y-%m') AS month, provider, SUM(cost_usd) "
        "FROM billing GROUP BY 1, 2 ORDER BY 1, 2"
    )
    months = sorted({r[0] for r in rows})
    providers = sorted({r[1] for r in rows})
    lookup = {(m, p): float(c) for m, p, c in rows}
    return {
        "labels": months,
        "series": {p: [round(lookup.get((m, p), 0.0), 2) for m in months] for p in providers},
    }


def daily_totals(data):
    """Zero-filled pandas Series of total USD cost per day (DatetimeIndex)."""
    if data.empty:
        return pd.Series(dtype=float)
    series = data.df.groupby("day")["cost_usd"].sum()
    index = pd.date_range(series.index.min(), series.index.max(), freq="D")
    return series.reindex(index, fill_value=0.0)


def service_daily_series(data):
    """{(provider, service): zero-filled daily Series from its first day to the last day of data}."""
    if data.empty:
        return {}
    last = data.df["day"].max()
    grouped = data.df.groupby(["provider", "service", "day"])["cost_usd"].sum()
    out = {}
    for (provider, service), sub in grouped.groupby(level=[0, 1]):
        series = sub.droplevel([0, 1])
        index = pd.date_range(series.index.min(), last, freq="D")
        out[(provider, service)] = series.reindex(index, fill_value=0.0)
    return out


def period_comparison(user, filters):
    """Compare the filtered period with the equal-length period just before it."""
    if not (filters.start and filters.end):
        return None
    length = (filters.end - filters.start).days + 1
    prev_end = filters.start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)
    current = total(load_frame(user, filters))
    previous = total(load_frame(user, replace(filters, start=prev_start, end=prev_end)))
    change = current - previous
    return {
        "current": round(current, 2),
        "previous": round(previous, 2),
        "change": round(change, 2),
        "change_pct": round(change / previous * 100, 1) if previous > 0 else None,
        "prev_start": prev_start,
        "prev_end": prev_end,
        "days": length,
    }


def latest_day(user):
    latest = BillingRecord.objects.filter(user=user).aggregate(m=Max("usage_start"))["m"]
    return latest.astimezone(dt_tz.utc).date() if latest else None


def default_range(user):
    """The last 30 days ending at the most recent billing record."""
    end = latest_day(user) or date.today()
    return end - timedelta(days=29), end


def filter_options(user):
    qs = BillingRecord.objects.filter(user=user)
    return {
        "services": list(qs.order_by("service").values_list("service", flat=True).distinct()),
        "projects": list(
            qs.exclude(project_or_subscription="")
            .order_by("project_or_subscription")
            .values_list("project_or_subscription", flat=True)
            .distinct()
        ),
    }
