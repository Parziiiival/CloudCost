import json
from types import SimpleNamespace

from django.test import override_settings

from analytics.engine import load_frame
from analytics.tests import daily_rows
from ingestion.tests import AWS_HEADER, ImportTestCase, csv_text
from recommendations import ai
from recommendations.models import Recommendation
from recommendations.rules import build_recommendations, generate_for_user
from resources.models import CloudResource
from django.utils import timezone

INSTANCE = "i-0a1b2c3d4e5f60001"


def resource(status, resource_id=INSTANCE, rtype="aws_ec2_instances"):
    return SimpleNamespace(
        status=status, resource_type=rtype, resource_id=resource_id,
        resource_name="web-1", provider="aws",
    )


class RuleTests(ImportTestCase):
    def load(self, days=10, cost=20):
        self.run_csv(csv_text(AWS_HEADER, *daily_rows(days, lambda i: cost)))
        return load_frame(self.user)

    def test_no_data_gives_no_recommendations(self):
        self.assertEqual(build_recommendations(load_frame(self.user), []), {})

    def test_stopped_resource_with_cost_is_flagged_with_evidence(self):
        recs = build_recommendations(self.load(), [resource("stopped")])
        rec = recs[f"idle_resource:aws:{INSTANCE}"]
        self.assertAlmostEqual(float(rec["savings"]), 200.0, places=2)
        self.assertTrue(rec["evidence"])
        self.assertIn("read-only", rec["explanation"])

    def test_running_resource_is_not_flagged_as_idle(self):
        recs = build_recommendations(self.load(), [resource("running")])
        self.assertFalse([k for k in recs if k.startswith("idle_resource")])

    def test_stopped_resource_without_cost_claims_no_saving(self):
        recs = build_recommendations(self.load(), [resource("stopped", "i-unbilled")])
        self.assertNotIn("idle_resource:aws:i-unbilled", recs)

    def test_concentration_has_no_savings_figure(self):
        recs = build_recommendations(self.load(), [])
        rec = recs["cost_concentration:aws:AmazonEC2"]
        self.assertIsNone(rec["savings"])
        self.assertAlmostEqual(float(rec["evidence"]["share_pct"]), 100.0, places=1)

    def test_generate_for_user_does_not_duplicate_and_keeps_status(self):
        self.load()
        CloudResource.objects.create(
            user=self.user, provider="aws", resource_id=INSTANCE,
            resource_type="aws_ec2_instances", status="stopped",
            last_seen_at=timezone.now(),
        )
        first = generate_for_user(self.user)
        self.assertGreater(first, 0)
        Recommendation.objects.filter(user=self.user).update(status="accepted")
        generate_for_user(self.user)
        recs = Recommendation.objects.filter(user=self.user)
        self.assertEqual(recs.count(), first)
        self.assertEqual(set(recs.values_list("status", flat=True)), {"accepted"})


class FakeResponse:
    def __init__(self, text):
        self.body = json.dumps(
            {"candidates": [{"content": {"parts": [{"text": text}]}}]}
        ).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


def opener_returning(text):
    def opener(request, timeout=None):
        return FakeResponse(text)
    return opener


class AIGuardTests(ImportTestCase):
    def setUp(self):
        super().setUp()
        self.rec = Recommendation.objects.create(
            user=self.user, category="idle_resource",
            title="Stopped instance web-1 still costs 200 USD",
            explanation="The instance is stopped but billed 200 USD in 30 days.",
            evidence={"cost_usd": 200, "window_days": 30},
            estimated_savings=200, dedupe_key="idle_resource:aws:web-1",
        )

    def test_invented_numbers_are_detected(self):
        source = ai.source_text(self.rec)
        self.assertFalse(ai.invented_numbers("It costs 200 USD over 30 days.", source))
        self.assertTrue(ai.invented_numbers("You could save 5000 USD.", source))

    @override_settings(GEMINI_API_KEY="")
    def test_disabled_without_key(self):
        self.assertFalse(ai.is_enabled())
        with self.assertRaises(ai.AIError):
            ai.explain(self.rec, opener=opener_returning("anything"))

    @override_settings(GEMINI_API_KEY="test-key-not-real")
    def test_reply_with_invented_figure_is_discarded(self):
        with self.assertRaises(ai.AIError) as ctx:
            ai.explain(self.rec, opener=opener_returning("Deleting it saves 5000 USD a year."))
        self.assertIn("discarded", str(ctx.exception))

    @override_settings(GEMINI_API_KEY="test-key-not-real")
    def test_clean_reply_is_returned(self):
        text = "The stopped instance still costs 200 USD over 30 days, mostly for storage."
        self.assertEqual(ai.explain(self.rec, opener=opener_returning(text)), text)

    @override_settings(GEMINI_API_KEY="test-key-not-real")
    def test_unusable_reply_is_an_error(self):
        def broken(request, timeout=None):
            raise TimeoutError("timed out")
        with self.assertRaises(ai.AIError):
            ai.explain(self.rec, opener=broken)
        with self.assertRaises(ai.AIError):
            ai.explain(self.rec, opener=opener_returning("   "))
