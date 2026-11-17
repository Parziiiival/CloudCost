"""Parse Infracost JSON (`infracost breakdown --path . --format json`).

Infracost figures are estimates of what Terraform code would cost per month.
They are stored and shown separately from actual billing and never added to it.
"""
import json
from decimal import Decimal, InvalidOperation


def _dec(value):
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _s(value):
    number = _dec(value)
    return None if number is None else str(number)


def parse_infracost(text):
    """Returns {"total": Decimal|None, "currency": str, "breakdown": [...]}.
    Raises ValueError with a user-readable message for unusable input."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        raise ValueError("The file is not valid JSON.")
    if not isinstance(data, dict) or not isinstance(data.get("projects"), list):
        raise ValueError(
            "This does not look like Infracost output (no 'projects' list). "
            "Create it with: infracost breakdown --path . --format json"
        )
    breakdown = []
    for project in data["projects"]:
        if not isinstance(project, dict):
            continue
        resources = (project.get("breakdown") or {}).get("resources") or []
        for res in resources:
            if not isinstance(res, dict):
                continue
            name = str(res.get("name") or "")[:200]
            breakdown.append(
                {
                    "project": str(project.get("name") or "")[:200],
                    "name": name,
                    "resource_type": str(res.get("resourceType") or name.split(".")[0])[:120],
                    "monthly_cost": _s(res.get("monthlyCost")),
                    "components": [
                        {
                            "name": str(c.get("name") or "")[:200],
                            "unit": str(c.get("unit") or "")[:60],
                            "quantity": _s(c.get("monthlyQuantity")),
                            "price": _s(c.get("price")),
                            "monthly_cost": _s(c.get("monthlyCost")),
                        }
                        for c in (res.get("costComponents") or [])
                        if isinstance(c, dict)
                    ],
                }
            )
    total = _dec(data.get("totalMonthlyCost"))
    if total is None:
        known = [Decimal(r["monthly_cost"]) for r in breakdown if r["monthly_cost"] is not None]
        total = sum(known, Decimal("0")) if known else None
    currency = str(data.get("currency") or "USD").upper()[:3]
    return {"total": total, "currency": currency, "breakdown": breakdown}
