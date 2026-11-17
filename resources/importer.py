"""Import a cloud resource inventory exported by CloudQuery.

CloudQuery is used for inventory only (what exists and its state), never for
billing. Accepts a JSON array or JSON Lines, e.g. the output of CloudQuery's
file destination.
"""
import json
from datetime import datetime, timezone as dt_tz

from django.utils import timezone

from cloud_accounts.models import PROVIDER_LABELS, CloudAccount

from .models import CloudResource

ID_KEYS = ("resource_id", "id", "arn", "instance_id", "self_link")
RESERVED = set(ID_KEYS) | {
    "_cq_table", "_cq_sync_time", "resource_type", "type", "provider", "name", "tags",
    "region", "location", "state", "status", "account_id", "subscription_id", "project_id",
}


def _load(text):
    text = (text or "").strip()
    if not text:
        raise ValueError("The file is empty.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = [json.loads(line) for line in text.splitlines() if line.strip()]
        except json.JSONDecodeError:
            raise ValueError("The file is not valid JSON or JSON Lines.")
    if isinstance(data, dict):
        data = data.get("resources") or data.get("rows") or [data]
    if not isinstance(data, list):
        raise ValueError("Expected a JSON array of resources.")
    return data


def _text(value, limit):
    if isinstance(value, dict):
        value = value.get("name") or value.get("Name") or ""
    return str(value or "").strip()[:limit]


def _seen_at(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return timezone.now()
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt_tz.utc)


def import_inventory(user, text):
    """Returns (imported, skipped). Raises ValueError for an unusable file."""
    items = _load(text)
    accounts = list(CloudAccount.objects.filter(user=user))
    by_identifier = {(a.provider, a.account_identifier): a for a in accounts}
    by_provider = {}
    for account in accounts:
        by_provider.setdefault(account.provider, []).append(account)

    imported = skipped = 0
    for item in items:
        if not isinstance(item, dict):
            skipped += 1
            continue
        rtype = _text(item.get("_cq_table") or item.get("resource_type") or item.get("type"), 120)
        provider = _text(item.get("provider"), 20).lower() or rtype.split("_")[0].lower()
        rid = next((_text(item.get(k), 500) for k in ID_KEYS if item.get(k)), "")
        if provider not in PROVIDER_LABELS or not rid:
            skipped += 1
            continue
        tags = item.get("tags") if isinstance(item.get("tags"), dict) else {}
        owner = _text(
            item.get("account_id") or item.get("subscription_id") or item.get("project_id"), 200
        )
        account = by_identifier.get((provider, owner))
        if account is None and len(by_provider.get(provider, [])) == 1:
            account = by_provider[provider][0]
        metadata = {
            str(k)[:60]: str(v)[:200]
            for k, v in list(item.items())[:40]
            if k not in RESERVED and isinstance(v, (str, int, float, bool))
        }
        CloudResource.objects.update_or_create(
            user=user,
            provider=provider,
            resource_id=rid,
            defaults={
                "cloud_account": account,
                "resource_type": rtype,
                "resource_name": _text(item.get("name") or tags.get("Name"), 200),
                "region": _text(item.get("region") or item.get("location"), 100),
                "status": _text(item.get("state") or item.get("status"), 60),
                "metadata": metadata,
                "last_seen_at": _seen_at(item.get("_cq_sync_time")),
            },
        )
        imported += 1
    return imported, skipped
