"""Rule-based optimization recommendations.

Each rule looks at billing data and the resource inventory and records the
evidence it used. A savings figure is attached only when billed cost supports
it. Nothing here changes a cloud resource: recommendations are for a person
to review and act on in their own cloud console.
"""
from datetime import timedelta
from decimal import Decimal

from analytics.engine import load_frame, service_daily_series
from cloud_accounts.models import PROVIDER_LABELS
from resources.models import CloudResource

from .models import Recommendation

IDLE_STATES = {"stopped", "stopping", "deallocated", "terminated", "suspended"}
UNATTACHED_STATES = {"available", "unattached", "unassociated", "reserved"}
UNATTACHED_TYPE_HINTS = ("disk", "volume", "public_ip", "address", "eip")
COMPUTE_HINTS = ("ec2", "virtual machines", "compute engine")

CONCENTRATION_SHARE = 0.40
GROWTH_PCT = 30.0
GROWTH_MIN_USD = 50.0
UNATTRIBUTED_SHARE = 0.10
COMMITMENT_MAX_CV = 0.25
READ_ONLY_NOTE = " CloudCost AI is read-only and will not change this resource."


def _usd(value):
    return f"${value:,.2f}"


def _resource_cost(costs, resource_id):
    rid = resource_id.lower()
    if rid in costs:
        return costs[rid]
    return costs.get(rid.rsplit("/", 1)[-1], 0.0)


def build_recommendations(data, resources):
    """Pure function. data: CostData; resources: iterable of CloudResource-like
    objects. Returns {dedupe_key: fields}."""
    found = {}
    if data.empty:
        return found
    df = data.df
    last = df["day"].max()
    start30 = last - timedelta(days=29)
    prior_start = start30 - timedelta(days=30)
    recent = df[df["day"] >= start30]
    prior = df[(df["day"] >= prior_start) & (df["day"] < start30)]
    total30 = float(recent["cost_usd"].sum())
    window = f"{start30:%Y-%m-%d} to {last:%Y-%m-%d}"
    history_days = (last - df["day"].min()).days + 1

    costs = recent[recent["resource_id"] != ""].groupby(
        recent["resource_id"].str.lower()
    )["cost_usd"].sum().to_dict()

    # 1 + 2: idle and unattached resources from the inventory.
    for res in resources:
        state = (res.status or "").lower()
        rtype = (res.resource_type or "").lower()
        cost = round(float(_resource_cost(costs, res.resource_id)), 2)
        label = res.resource_name or res.resource_id
        provider = PROVIDER_LABELS.get(res.provider, res.provider)
        evidence = {
            "resource_id": res.resource_id,
            "resource_type": res.resource_type,
            "inventory_status": res.status,
            "billed_cost_last_30_days_usd": cost,
            "window": window,
        }
        if state in IDLE_STATES and cost > 0:
            found[f"idle_resource:{res.provider}:{res.resource_id}"] = {
                "category": "idle_resource",
                "title": f"{provider} resource '{label}' is {state} but still billed",
                "explanation": (
                    f"The inventory lists this resource as '{res.status}', yet it was billed "
                    f"{_usd(cost)} over the last 30 days ({window}), typically for attached "
                    "storage or reserved addresses. If it is no longer needed, removing it "
                    "would stop that charge; if it is needed, no action is required."
                    + READ_ONLY_NOTE
                ),
                "evidence": evidence,
                "savings": cost,
            }
        elif state in UNATTACHED_STATES and any(h in rtype for h in UNATTACHED_TYPE_HINTS):
            text = (
                f"The inventory lists this {res.resource_type or 'resource'} as "
                f"'{res.status}', meaning it is not attached to anything."
            )
            if cost > 0:
                text += f" It was billed {_usd(cost)} over the last 30 days ({window})."
            else:
                text += (
                    " No billed cost could be matched to it in the last 30 days, so no "
                    "savings figure is shown."
                )
            found[f"unattached_resource:{res.provider}:{res.resource_id}"] = {
                "category": "unattached_resource",
                "title": f"{provider} resource '{label}' is unattached",
                "explanation": text + " Review whether it can be deleted or should be reattached."
                + READ_ONLY_NOTE,
                "evidence": evidence,
                "savings": cost if cost > 0 else None,
            }

    # 3 + 4: concentration and growth per service.
    recent_by_service = recent.groupby(["provider", "service"])["cost_usd"].sum()
    prior_by_service = prior.groupby(["provider", "service"])["cost_usd"].sum()
    for (provider, service), cost in recent_by_service.items():
        cost = float(cost)
        name = f"{PROVIDER_LABELS.get(provider, provider)} {service}"
        if total30 > 0 and cost / total30 > CONCENTRATION_SHARE:
            share = round(cost / total30 * 100, 1)
            found[f"cost_concentration:{provider}:{service}"] = {
                "category": "cost_concentration",
                "title": f"{name} is {share}% of total spend",
                "explanation": (
                    f"{name} cost {_usd(cost)} of {_usd(total30)} total over the last 30 days "
                    f"({window}), which is {share}% of spend. A single service this large is "
                    "the most effective place to look for right-sizing or pricing options. "
                    "No savings figure is shown because none can be derived from billing data alone."
                ),
                "evidence": {
                    "service_cost_usd": round(cost, 2),
                    "total_cost_usd": round(total30, 2),
                    "share_pct": share,
                    "window": window,
                },
                "savings": None,
            }
        before = float(prior_by_service.get((provider, service), 0.0))
        if history_days >= 60 and before > 0:
            increase = cost - before
            pct = increase / before * 100
            if pct > GROWTH_PCT and increase >= GROWTH_MIN_USD:
                found[f"cost_growth:{provider}:{service}"] = {
                    "category": "cost_growth",
                    "title": f"{name} spend grew {pct:.1f}% in 30 days",
                    "explanation": (
                        f"{name} cost {_usd(cost)} in the last 30 days ({window}) compared with "
                        f"{_usd(before)} in the 30 days before, an increase of {_usd(increase)} "
                        f"({pct:.1f}%). Check whether the growth matches expected usage. "
                        "No savings figure is shown because growth may be intentional."
                    ),
                    "evidence": {
                        "last_30_days_usd": round(cost, 2),
                        "previous_30_days_usd": round(before, 2),
                        "increase_usd": round(increase, 2),
                        "increase_pct": round(pct, 1),
                        "window": window,
                    },
                    "savings": None,
                }

    # 5: spend that cannot be attributed.
    if total30 > 0:
        for column, what, key in (
            ("resource_id", "a resource ID", "resource"),
            ("project", "a project or subscription", "project"),
        ):
            missing = float(recent[recent[column] == ""]["cost_usd"].sum())
            if missing / total30 > UNATTRIBUTED_SHARE:
                share = round(missing / total30 * 100, 1)
                found[f"unattributed_spend:{key}"] = {
                    "category": "unattributed_spend",
                    "title": f"{share}% of spend has no {key} attribution",
                    "explanation": (
                        f"{_usd(missing)} of {_usd(total30)} over the last 30 days ({window}) "
                        f"is not linked to {what}. Spend that cannot be attributed cannot be "
                        "assigned to an owner or optimized. Enabling resource-level detail and "
                        "tagging in the billing export would close this gap."
                    ),
                    "evidence": {
                        "unattributed_usd": round(missing, 2),
                        "total_cost_usd": round(total30, 2),
                        "share_pct": share,
                        "window": window,
                    },
                    "savings": None,
                }

    # 6: steady compute spend that may suit a commitment.
    for (provider, service), series in service_daily_series(data).items():
        if not any(h in service.lower() for h in COMPUTE_HINTS):
            continue
        last30 = series[series.index >= start30]
        if len(last30) < 30 or (last30 <= 0).any():
            continue
        mean = float(last30.mean())
        cv = float(last30.std() / mean) if mean > 0 else 1.0
        if cv < COMMITMENT_MAX_CV:
            name = f"{PROVIDER_LABELS.get(provider, provider)} {service}"
            found[f"commitment:{provider}:{service}"] = {
                "category": "commitment",
                "title": f"{name} spend is steady enough to evaluate a commitment",
                "explanation": (
                    f"{name} was billed every day of the last 30 days ({window}), averaging "
                    f"{_usd(mean)} per day with a minimum of {_usd(float(last30.min()))} "
                    f"(coefficient of variation {cv:.2f}). Steady baseline usage like this is "
                    "what reserved-capacity or savings-plan pricing is designed for. No savings "
                    "figure is shown: the discount depends on provider terms and on how long "
                    "the workload will keep running."
                ),
                "evidence": {
                    "average_daily_usd": round(mean, 2),
                    "minimum_daily_usd": round(float(last30.min()), 2),
                    "coefficient_of_variation": round(cv, 2),
                    "window": window,
                },
                "savings": None,
            }
    return found


def generate_for_user(user):
    """Recompute recommendations for a user. Returns the number generated."""
    data = load_frame(user)
    found = build_recommendations(data, CloudResource.objects.filter(user=user))
    for key, item in found.items():
        savings = None if item["savings"] is None else Decimal(f"{item['savings']:.2f}")
        rec = Recommendation.objects.filter(user=user, dedupe_key=key[:300]).first()
        if rec is None:
            Recommendation.objects.create(
                user=user,
                dedupe_key=key[:300],
                category=item["category"],
                title=item["title"][:200],
                explanation=item["explanation"],
                evidence=item["evidence"],
                estimated_savings=savings,
                currency="USD",
            )
            continue
        if rec.evidence != item["evidence"]:
            rec.ai_explanation = ""  # written for figures that no longer apply
        rec.category = item["category"]
        rec.title = item["title"][:200]
        rec.explanation = item["explanation"]
        rec.evidence = item["evidence"]
        rec.estimated_savings = savings
        rec.save()  # status and review_note set by a person are kept
    stale = Recommendation.objects.filter(user=user, status="open")
    stale.exclude(dedupe_key__in=[k[:300] for k in found]).delete()
    return len(found)
