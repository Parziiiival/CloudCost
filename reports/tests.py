import csv
import io

from django.test import Client
from django.urls import reverse

from ingestion.tests import AWS_HEADER, ImportTestCase, aws_row, csv_text
from reports.views import safe_cell


class SafeCellTests(ImportTestCase):
    def test_formula_like_text_is_neutralised(self):
        for value in ("=SUM(A1:A9)", "+1", "-1", "@cmd", "\tx"):
            self.assertEqual(safe_cell(value), "'" + value)

    def test_plain_values_are_unchanged(self):
        self.assertEqual(safe_cell("AmazonEC2"), "AmazonEC2")
        self.assertEqual(safe_cell(-12.5), -12.5)
        self.assertEqual(safe_cell(""), "")


class ReportViewTests(ImportTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client(HTTP_HOST="localhost")
        self.client.force_login(self.user)
        self.run_csv(
            csv_text(
                AWS_HEADER,
                aws_row(cost="12.5", service="AmazonEC2", resource="i-1"),
                aws_row(cost="7.5", service="AmazonEC2", resource="i-2"),
                aws_row(cost="3", service="=HYPERLINK(1)", resource="i-3"),
            )
        )

    def rows(self, name):
        response = self.client.get(reverse(name))
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("attachment", response["Content-Disposition"])
        return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))

    def test_costs_csv_groups_and_totals(self):
        rows = self.rows("report_costs_csv")
        self.assertEqual(
            rows[0], ["date", "provider", "service", "region", "project", "cost_usd"]
        )
        by_service = {r[2]: r for r in rows[1:]}
        self.assertAlmostEqual(float(by_service["AmazonEC2"][5]), 20.0, places=2)
        self.assertEqual(by_service["AmazonEC2"][0], "2026-07-20")
        self.assertIn("'=HYPERLINK(1)", by_service)

    def test_other_csvs_and_summary_render_when_empty(self):
        self.assertEqual(len(self.rows("report_anomalies_csv")), 1)
        self.assertEqual(len(self.rows("report_recommendations_csv")), 1)
        self.assertEqual(self.client.get(reverse("report_summary")).status_code, 200)
        self.assertEqual(self.client.get(reverse("reports")).status_code, 200)
