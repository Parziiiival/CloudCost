"""Optional plain-language explanations from the Gemini API.

The model only rewords a recommendation that the rules already produced. It is
given the computed evidence and told not to add figures; any reply containing a
number that is not in the evidence is discarded. Nothing is sent unless a key
is configured and the user asks for an explanation.
"""
import json
import re
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

from django.conf import settings

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


class AIError(Exception):
    """User-readable reason an explanation could not be produced."""


def is_enabled():
    return bool(getattr(settings, "GEMINI_API_KEY", ""))


def _numbers(text):
    out = set()
    for raw in NUMBER_RE.findall(text or ""):
        try:
            out.add(Decimal(raw.replace(",", "").rstrip(".")).normalize())
        except InvalidOperation:
            continue
    return out


def source_text(rec):
    savings = "" if rec.estimated_savings is None else str(rec.estimated_savings)
    return "\n".join([rec.title, rec.explanation, json.dumps(rec.evidence, sort_keys=True), savings])


def invented_numbers(reply, source):
    """Numbers in the reply that do not appear in the source material."""
    return _numbers(reply) - _numbers(source)


def build_prompt(rec):
    return (
        "You are helping a cloud cost analyst understand one optimization recommendation.\n"
        "Rewrite it as a short plain-language explanation (at most 120 words, prose only, "
        "no lists) covering what was observed and what a person could check next.\n"
        "Rules: use only the figures given below, exactly as written. Do not calculate, "
        "estimate or add any new number, percentage, date or savings amount. Do not promise "
        "savings. Do not suggest that anything will be changed automatically.\n\n"
        f"Title: {rec.title}\n"
        f"Rule-based explanation: {rec.explanation}\n"
        f"Evidence (JSON): {json.dumps(rec.evidence, sort_keys=True)}\n"
    )


def explain(rec, opener=urllib.request.urlopen):
    if not is_enabled():
        raise AIError("AI explanations are not configured (GEMINI_API_KEY is not set).")
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": build_prompt(rec)}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 400},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT.format(model=settings.GEMINI_MODEL),
        data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": settings.GEMINI_API_KEY},
        method="POST",
    )
    try:
        with opener(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        parts = payload["candidates"][0]["content"]["parts"]
        reply = "".join(p.get("text", "") for p in parts).strip()
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError):
        # The error detail may contain the request; keep it out of the UI and logs.
        raise AIError("The AI service could not be reached or returned an unusable reply.")
    if not reply:
        raise AIError("The AI service returned an empty reply.")
    if invented_numbers(reply, source_text(rec)):
        raise AIError(
            "The AI explanation was discarded because it contained figures that are "
            "not in the computed evidence."
        )
    return reply[:2000]
