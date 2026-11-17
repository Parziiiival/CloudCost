"""Provider-specific CSV adapters.

Each adapter maps a provider's billing export columns onto the common
BillingRecord schema. Parsing is strict about money and dates (a row that
cannot be trusted is rejected with a reason) and lenient about optional
descriptive fields.
"""
import hashlib
import re
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal, InvalidOperation

REQUIRED = ("service", "usage_start", "cost")
MAX_ABS_COST = Decimal("1000000000")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

GENERIC = {
    "billing_account": ["billing_account", "billing_account_id"],
    "project_or_subscription": ["project_or_subscription", "project", "subscription", "account"],
    "service": ["service", "service_name"],
    "resource_id": ["resource_id", "resource"],
    "region": ["region", "location"],
    "usage_start": ["usage_start", "usage_date", "date"],
    "usage_end": ["usage_end"],
    "usage_quantity": ["usage_quantity", "quantity"],
    "usage_unit": ["usage_unit", "unit"],
    "cost": ["cost", "amount"],
    "currency": ["currency", "currency_code"],
}

FIELD_CANDIDATES = {
    "aws": {
        "billing_account": ["bill/PayerAccountId"],
        "project_or_subscription": ["lineItem/UsageAccountId"],
        "service": ["lineItem/ProductCode", "product/ProductName"],
        "resource_id": ["lineItem/ResourceId"],
        "region": ["product/region"],
        "usage_start": ["lineItem/UsageStartDate"],
        "usage_end": ["lineItem/UsageEndDate"],
        "usage_quantity": ["lineItem/UsageAmount"],
        "usage_unit": ["pricing/unit"],
        "cost": ["lineItem/UnblendedCost"],
        "currency": ["lineItem/CurrencyCode"],
    },
    "azure": {
        "billing_account": ["BillingAccountId"],
        "project_or_subscription": ["SubscriptionName", "SubscriptionId"],
        "service": ["MeterCategory", "ServiceName"],
        "resource_id": ["ResourceId"],
        "region": ["ResourceLocation"],
        "usage_start": ["Date", "UsageDate"],
        "usage_end": [],
        "usage_quantity": ["Quantity"],
        "usage_unit": ["UnitOfMeasure"],
        "cost": ["CostInBillingCurrency", "Cost"],
        "currency": ["BillingCurrencyCode", "BillingCurrency"],
    },
    "gcp": {
        "billing_account": ["billing_account_id"],
        "project_or_subscription": ["project.id", "project_id"],
        "service": ["service.description"],
        "resource_id": ["resource.name"],
        "region": ["location.region"],
        "usage_start": ["usage_start_time"],
        "usage_end": ["usage_end_time"],
        "usage_quantity": ["usage.amount"],
        "usage_unit": ["usage.unit"],
        "cost": ["cost"],
        "currency": ["currency"],
    },
}

MAX_LEN = {
    "billing_account": 200,
    "project_or_subscription": 200,
    "service": 200,
    "resource_id": 500,
    "region": 100,
    "usage_unit": 60,
}

# Slash dates are read month-first (the format Azure cost exports use).
DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%Y %H:%M:%S", "%Y/%m/%d", "%d-%b-%Y", "%Y%m%d")


class RowError(Exception):
    """A row that cannot be imported; str(exc) is a user-readable reason."""


def resolve_columns(provider, header):
    """Map schema fields to the actual column names in this file.

    Returns (mapping, missing_required). Matching is case-insensitive.
    """
    lookup = {}
    for name in header or []:
        if name is not None:
            lookup.setdefault(name.strip().lower(), name)
    mapping = {}
    for field, generic in GENERIC.items():
        for candidate in FIELD_CANDIDATES.get(provider, {}).get(field, []) + generic:
            actual = lookup.get(candidate.lower())
            if actual is not None:
                mapping[field] = actual
                break
    missing = [f for f in REQUIRED if f not in mapping]
    return mapping, missing


def parse_datetime(value):
    text = (value or "").strip()
    if not text:
        raise RowError("usage date is empty")
    candidate = text
    if candidate.upper().endswith(" UTC"):
        candidate = candidate[:-4] + "+00:00"
    elif candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    parsed = None
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        for fmt in DATE_FORMATS:
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        raise RowError(f"unrecognised date '{text[:40]}'")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_tz.utc)
    else:
        parsed = parsed.astimezone(dt_tz.utc)
    if not 2000 <= parsed.year <= 2100:
        raise RowError(f"date out of range '{text[:40]}'")
    return parsed


def parse_cost(value):
    text = (value or "").strip().replace(",", "").replace("$", "")
    if not text:
        raise RowError("cost is empty")
    try:
        cost = Decimal(text)
    except InvalidOperation:
        raise RowError(f"cost is not a number '{text[:30]}'")
    if not cost.is_finite():
        raise RowError("cost is not a finite number")
    if abs(cost) > MAX_ABS_COST:
        raise RowError("cost is implausibly large (over 1,000,000,000)")
    return cost.quantize(Decimal("0.000001"))


def parse_quantity(value):
    text = (value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        qty = Decimal(text)
    except InvalidOperation:
        return None
    if not qty.is_finite() or abs(qty) > Decimal("1e17"):
        return None
    return qty.quantize(Decimal("0.000001"))


def _plain(number):
    return "" if number is None else format(number.normalize(), "f")


def parse_row(provider, mapping, row):
    """Turn one CSV row into normalized BillingRecord field values."""

    def get(field):
        column = mapping.get(field)
        if column is None:
            return ""
        return (row.get(column) or "").strip()

    service = get("service")
    if not service:
        raise RowError("service is empty")
    usage_start = parse_datetime(get("usage_start"))
    end_text = get("usage_end")
    usage_end = parse_datetime(end_text) if end_text else usage_start + timedelta(days=1)
    if usage_end < usage_start:
        raise RowError("usage end is before usage start")
    cost = parse_cost(get("cost"))
    currency = get("currency").upper() or "USD"
    if not CURRENCY_RE.match(currency):
        raise RowError(f"invalid currency code '{currency[:10]}'")

    record = {
        "provider": provider,
        "service": service,
        "usage_start": usage_start,
        "usage_end": usage_end,
        "usage_quantity": parse_quantity(get("usage_quantity")),
        "cost": cost,
        "currency": currency,
    }
    for field, limit in MAX_LEN.items():
        if field != "service":
            record[field] = get(field)[:limit]
    record["service"] = service[: MAX_LEN["service"]]

    # The hash identifies a billing line item, so re-importing the same export
    # (or an overlapping one) never double-counts spend.
    identity = "|".join(
        [
            provider,
            record["billing_account"],
            record["project_or_subscription"],
            record["service"],
            record["resource_id"],
            record["region"],
            usage_start.isoformat(),
            usage_end.isoformat(),
            _plain(record["usage_quantity"]),
            record["usage_unit"],
            _plain(cost),
            currency,
        ]
    )
    record["record_hash"] = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return record
