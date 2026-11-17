"""Access control: sign-in is required and users only ever see their own data."""
from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from alerts.models import CostAnomaly
from cloud_accounts.models import CloudAccount
from estimates.models import InfracostEstimate
from ingestion.models import ImportJob
from ingestion.services import run_import
from ingestion.tests import AWS_HEADER, ImportTestCase, aws_row, csv_text
from recommendations.models import Recommendation

PAGES = [
    "dashboard", "cloud_accounts", "cloud_account_add", "imports", "import_upload",
    "resources", "resources_import", "estimates", "estimate_upload", "anomalies",
    "forecast", "recommendations", "reports", "report_costs_csv",
    "report_anomalies_csv", "report_recommendations_csv", "report_summary",
]


class AccessTests(ImportTestCase):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.bob = User.objects.create_user("bob", password="pw-for-tests-2")
        bob_account = CloudAccount.objects.create(
            user=self.bob, provider="aws", account_name="Bob AWS",
            account_identifier="bob-secret-account",
        )
        self.bob_job = ImportJob.objects.create(
            user=self.bob, cloud_account=bob_account, source_file="bob-secret.csv",
        )
        run_import(
            self.bob_job,
            SimpleUploadedFile(
                "bob.csv",
                csv_text(
                    AWS_HEADER,
                    aws_row(cost="4242", service="BobSecretService", resource="i-bob"),
                ).encode(),
            ),
        )
        self.bob_estimate = InfracostEstimate.objects.create(
            user=self.bob, name="Bob secret estimate", source_file="bob.json",
            total_monthly_cost=10, breakdown=[],
        )
        self.bob_anomaly = CostAnomaly.objects.create(
            user=self.bob, provider="aws", service="BobSecretService",
            usage_date=date(2026, 7, 20), observed_cost=4242, expected_cost=10,
            deviation=4232, deviation_pct=42320, method="pct_threshold",
            explanation="Bob secret explanation",
        )
        self.bob_rec = Recommendation.objects.create(
            user=self.bob, category="idle_resource", title="Bob secret recommendation",
            explanation="x", evidence={}, dedupe_key="bob-key",
        )
        self.client = Client(HTTP_HOST="localhost")

    def test_anonymous_users_are_sent_to_login(self):
        for name in PAGES:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn(reverse("login"), response["Location"], name)
        response = self.client.get(reverse("import_detail", args=[self.bob_job.pk]))
        self.assertEqual(response.status_code, 302)
        response = self.client.post(reverse("pipeline_run"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_pages_render_for_a_user_with_no_data(self):
        self.client.force_login(self.user)
        for name in PAGES:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_other_users_objects_are_not_found(self):
        self.client.force_login(self.user)
        for name, pk in [
            ("import_detail", self.bob_job.pk),
            ("estimate_detail", self.bob_estimate.pk),
        ]:
            self.assertEqual(self.client.get(reverse(name, args=[pk])).status_code, 404, name)

    def test_other_users_objects_cannot_be_changed(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("anomaly_status", args=[self.bob_anomaly.pk]), {"status": "dismissed"}
        )
        self.assertEqual(response.status_code, 404)
        response = self.client.post(
            reverse("recommendation_status", args=[self.bob_rec.pk]),
            {"status": "rejected", "review_note": "nope"},
        )
        self.assertEqual(response.status_code, 404)
        response = self.client.post(reverse("recommendation_explain", args=[self.bob_rec.pk]))
        self.assertEqual(response.status_code, 404)
        self.bob_anomaly.refresh_from_db()
        self.bob_rec.refresh_from_db()
        self.assertEqual(self.bob_anomaly.status, "open")
        self.assertEqual(self.bob_rec.status, "open")

    def test_lists_and_exports_never_show_other_users_data(self):
        self.client.force_login(self.user)
        for name in PAGES:
            body = self.client.get(reverse(name)).content.decode()
            self.assertNotIn("BobSecret", body, name)
            self.assertNotIn("Bob secret", body, name)
            self.assertNotIn("bob-secret", body, name)
            self.assertNotIn("4242", body, name)

    def test_owner_can_see_and_update_own_objects(self):
        self.client.force_login(self.bob)
        self.assertEqual(
            self.client.get(reverse("import_detail", args=[self.bob_job.pk])).status_code, 200
        )
        self.assertContains(self.client.get(reverse("anomalies")), "BobSecretService")
        response = self.client.post(
            reverse("anomaly_status", args=[self.bob_anomaly.pk]), {"status": "acknowledged"}
        )
        self.assertEqual(response.status_code, 302)
        self.bob_anomaly.refresh_from_db()
        self.assertEqual(self.bob_anomaly.status, "acknowledged")
        response = self.client.post(
            reverse("recommendation_status", args=[self.bob_rec.pk]),
            {"status": "accepted", "review_note": "agreed"},
        )
        self.assertEqual(response.status_code, 302)
        self.bob_rec.refresh_from_db()
        self.assertEqual(self.bob_rec.status, "accepted")
        self.assertEqual(self.bob_rec.review_note, "agreed")

    def test_invalid_status_is_rejected(self):
        self.client.force_login(self.bob)
        self.client.post(
            reverse("anomaly_status", args=[self.bob_anomaly.pk]), {"status": "deleted"}
        )
        self.bob_anomaly.refresh_from_db()
        self.assertEqual(self.bob_anomaly.status, "open")

    def test_status_change_requires_post(self):
        self.client.force_login(self.bob)
        response = self.client.get(reverse("anomaly_status", args=[self.bob_anomaly.pk]))
        self.assertEqual(response.status_code, 405)

    def test_signup_creates_an_account_and_signs_in(self):
        response = self.client.post(
            reverse("signup"),
            {"username": "carol", "password1": "a-Long-pass-9471", "password2": "a-Long-pass-9471"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(get_user_model().objects.filter(username="carol").exists())
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
