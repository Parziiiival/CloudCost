from datetime import datetime, timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from billing.models import BillingRecord
from cloud_accounts.models import CloudAccount
from ingestion.adapters import RowError, parse_datetime
from ingestion.models import ImportJob
from ingestion.services import run_import

AWS_HEADER = (
    "bill/PayerAccountId,lineItem/UsageAccountId,lineItem/ProductCode,"
    "lineItem/ResourceId,product/region,lineItem/UsageStartDate,"
    "lineItem/UsageEndDate,lineItem/UsageAmount,pricing/unit,"
    "lineItem/UnblendedCost,lineItem/CurrencyCode"
)
AZURE_HEADER = (
    "BillingAccountId,SubscriptionName,MeterCategory,ResourceId,"
    "ResourceLocation,Date,Quantity,UnitOfMeasure,CostInBillingCurrency,"
    "BillingCurrencyCode"
)
GCP_HEADER = (
    "billing_account_id,project.id,service.description,resource.name,"
    "location.region,usage_start_time,usage_end_time,usage.amount,"
    "usage.unit,cost,currency"
)


def aws_row(cost="96.3246", start="2026-07-20T00:00:00Z", end="2026-07-21T00:00:00Z",
            service="AmazonEC2", currency="USD", resource="i-0a1b2c3d4e5f60001"):
    return (
        f"111122223333,111122223333,{service},{resource},us-east-1,"
        f"{start},{end},24,Hrs,{cost},{currency}"
    )


def csv_text(header, *rows):
    return "\n".join([header, *rows]) + "\n"


class ImportTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("alice", password="pw-for-tests-1")
        self.accounts = {
            provider: CloudAccount.objects.create(
                user=self.user,
                provider=provider,
                account_name=f"{provider} test",
                account_identifier=f"{provider}-001",
            )
            for provider in ("aws", "azure", "gcp")
        }

    def run_csv(self, content, provider="aws"):
        job = ImportJob.objects.create(
            user=self.user,
            cloud_account=self.accounts[provider],
            source_file="test.csv",
        )
        if isinstance(content, str):
            content = content.encode("utf-8")
        run_import(job, SimpleUploadedFile("test.csv", content))
        job.refresh_from_db()
        return job


class ValidFilesTests(ImportTestCase):
    def test_aws_file_is_normalized(self):
        job = self.run_csv(csv_text(AWS_HEADER, aws_row()))
        self.assertEqual(job.status, ImportJob.COMPLETED)
        self.assertEqual(job.records_imported, 1)
        rec = BillingRecord.objects.get()
        self.assertEqual(rec.provider, "aws")
        self.assertEqual(rec.service, "AmazonEC2")
        self.assertEqual(rec.region, "us-east-1")
        self.assertEqual(rec.resource_id, "i-0a1b2c3d4e5f60001")
        self.assertEqual(rec.cost, Decimal("96.3246"))
        self.assertEqual(rec.currency, "USD")
        self.assertEqual(rec.usage_start, datetime(2026, 7, 20, tzinfo=timezone.utc))
        self.assertEqual(rec.user, self.user)

    def test_azure_file_is_normalized(self):
        row = (
            "contoso-billing-001,Contoso-Prod,Virtual Machines,"
            "/subscriptions/abc/vm-web-01,westeurope,07/20/2026,24,1 Hour,59.7093,EUR"
        )
        job = self.run_csv(csv_text(AZURE_HEADER, row), provider="azure")
        self.assertEqual(job.status, ImportJob.COMPLETED)
        rec = BillingRecord.objects.get()
        self.assertEqual(rec.provider, "azure")
        self.assertEqual(rec.service, "Virtual Machines")
        self.assertEqual(rec.project_or_subscription, "Contoso-Prod")
        self.assertEqual(rec.currency, "EUR")
        self.assertEqual(rec.usage_start.date().isoformat(), "2026-07-20")

    def test_gcp_file_is_normalized(self):
        row = (
            "01ABCD-234EFG-567HIJ,acme-web-prod,Compute Engine,"
            "projects/acme-web-prod/zones/us-central1-a/instances/web-1,us-central1,"
            "2026-07-20 00:00:00 UTC,2026-07-21 00:00:00 UTC,86400,seconds,53.6052,USD"
        )
        job = self.run_csv(csv_text(GCP_HEADER, row), provider="gcp")
        self.assertEqual(job.status, ImportJob.COMPLETED)
        rec = BillingRecord.objects.get()
        self.assertEqual(rec.provider, "gcp")
        self.assertEqual(rec.service, "Compute Engine")
        self.assertEqual(rec.project_or_subscription, "acme-web-prod")
        self.assertEqual(rec.usage_start, datetime(2026, 7, 20, tzinfo=timezone.utc))


class BadFilesTests(ImportTestCase):
    def test_missing_required_columns_fails_the_import(self):
        job = self.run_csv("lineItem/ProductCode,product/region\nAmazonEC2,us-east-1\n")
        self.assertEqual(job.status, ImportJob.FAILED)
        self.assertIn("Missing required column(s)", job.error_message)
        self.assertEqual(BillingRecord.objects.count(), 0)

    def test_wrong_provider_file_fails(self):
        job = self.run_csv(csv_text(GCP_HEADER, "a,b,c,d,e,2026-07-20,2026-07-21,1,s,1,USD"))
        self.assertEqual(job.status, ImportJob.FAILED)
        self.assertIn("Missing required column(s)", job.error_message)

    def test_empty_file_fails(self):
        job = self.run_csv("")
        self.assertEqual(job.status, ImportJob.FAILED)
        self.assertEqual(job.error_message, "The file is empty.")

    def test_header_only_file_imports_nothing(self):
        job = self.run_csv(AWS_HEADER + "\n")
        self.assertEqual(job.records_imported, 0)
        self.assertEqual(BillingRecord.objects.count(), 0)

    def test_non_utf8_file_fails(self):
        job = self.run_csv(b"\xff\xfe\x00\x81\x8d bad bytes")
        self.assertEqual(job.status, ImportJob.FAILED)
        self.assertIn("UTF-8", job.error_message)

    def test_malformed_rows_are_rejected_with_reasons(self):
        job = self.run_csv(csv_text(
            AWS_HEADER,
            aws_row(),
            aws_row(cost="abc", resource="r2"),
            aws_row(start="not-a-date", resource="r3"),
            aws_row(service="", resource="r4"),
            aws_row(cost="", resource="r5"),
        ))
        self.assertEqual(job.status, ImportJob.COMPLETED_WITH_ERRORS)
        self.assertEqual(job.records_imported, 1)
        self.assertEqual(job.records_rejected, 4)
        reasons = " | ".join(e["reason"] for e in job.error_log)
        self.assertIn("cost is not a number", reasons)
        self.assertIn("unrecognised date", reasons)
        self.assertIn("service is empty", reasons)
        self.assertIn("cost is empty", reasons)
        self.assertEqual([e["row"] for e in job.error_log], [3, 4, 5, 6])

    def test_all_rows_bad_fails_without_saving(self):
        job = self.run_csv(csv_text(AWS_HEADER, aws_row(cost="abc")))
        self.assertEqual(job.status, ImportJob.FAILED)
        self.assertEqual(BillingRecord.objects.count(), 0)


class CostValueTests(ImportTestCase):
    def test_negative_and_zero_costs_are_kept(self):
        job = self.run_csv(csv_text(
            AWS_HEADER,
            aws_row(cost="-12.50", resource="credit"),
            aws_row(cost="0", resource="free"),
        ))
        self.assertEqual(job.records_imported, 2)
        self.assertEqual(job.records_rejected, 0)
        costs = sorted(BillingRecord.objects.values_list("cost", flat=True))
        self.assertEqual(costs, [Decimal("-12.50"), Decimal("0")])

    def test_implausibly_large_cost_is_rejected(self):
        job = self.run_csv(csv_text(
            AWS_HEADER, aws_row(), aws_row(cost="5000000000", resource="big"),
        ))
        self.assertEqual(job.records_imported, 1)
        self.assertEqual(job.records_rejected, 1)
        self.assertIn("implausibly large", job.error_log[0]["reason"])

    def test_non_finite_cost_is_rejected(self):
        job = self.run_csv(csv_text(
            AWS_HEADER, aws_row(), aws_row(cost="NaN", resource="n"),
            aws_row(cost="Infinity", resource="i"),
        ))
        self.assertEqual(job.records_imported, 1)
        self.assertEqual(job.records_rejected, 2)

    def test_invalid_currency_is_rejected_and_code_is_uppercased(self):
        job = self.run_csv(csv_text(
            AWS_HEADER,
            aws_row(currency="eur"),
            aws_row(currency="DOLLARS", resource="bad"),
        ))
        self.assertEqual(job.records_imported, 1)
        self.assertEqual(job.records_rejected, 1)
        self.assertIn("invalid currency code", job.error_log[0]["reason"])
        self.assertEqual(BillingRecord.objects.get().currency, "EUR")

    def test_usage_end_before_start_is_rejected(self):
        job = self.run_csv(csv_text(
            AWS_HEADER, aws_row(),
            aws_row(start="2026-07-21T00:00:00Z", end="2026-07-20T00:00:00Z", resource="x"),
        ))
        self.assertEqual(job.records_rejected, 1)
        self.assertIn("usage end is before usage start", job.error_log[0]["reason"])


class DuplicateTests(ImportTestCase):
    def test_duplicate_rows_in_one_file_count_once(self):
        job = self.run_csv(csv_text(AWS_HEADER, aws_row(), aws_row(), aws_row()))
        self.assertEqual(job.records_imported, 1)
        self.assertEqual(job.records_duplicate, 2)
        self.assertEqual(BillingRecord.objects.count(), 1)

    def test_reimporting_a_file_does_not_double_count(self):
        content = csv_text(AWS_HEADER, aws_row(), aws_row(resource="other"))
        self.run_csv(content)
        second = self.run_csv(content)
        self.assertEqual(second.records_imported, 0)
        self.assertEqual(second.records_duplicate, 2)
        self.assertEqual(BillingRecord.objects.count(), 2)

    def test_same_file_for_another_user_is_not_a_duplicate(self):
        content = csv_text(AWS_HEADER, aws_row())
        self.run_csv(content)
        other = get_user_model().objects.create_user("bob", password="pw-for-tests-2")
        account = CloudAccount.objects.create(
            user=other, provider="aws", account_name="b", account_identifier="b-1",
        )
        job = ImportJob.objects.create(user=other, cloud_account=account, source_file="t.csv")
        run_import(job, SimpleUploadedFile("t.csv", content.encode()))
        job.refresh_from_db()
        self.assertEqual(job.records_imported, 1)
        self.assertEqual(BillingRecord.objects.filter(user=other).count(), 1)


class DateParsingTests(TestCase):
    def test_supported_formats_give_the_same_day(self):
        for text in (
            "2026-07-20",
            "2026-07-20T00:00:00Z",
            "2026-07-20 00:00:00 UTC",
            "07/20/2026",
            "2026/07/20",
            "20-Jul-2026",
            "20260720",
        ):
            with self.subTest(text=text):
                parsed = parse_datetime(text)
                self.assertEqual(parsed, datetime(2026, 7, 20, tzinfo=timezone.utc))

    def test_offset_is_converted_to_utc(self):
        parsed = parse_datetime("2026-07-20T02:00:00+05:30")
        self.assertEqual(
            parsed.astimezone(timezone.utc),
            datetime(2026, 7, 19, 20, 30, tzinfo=timezone.utc),
        )

    def test_naive_values_are_treated_as_utc(self):
        self.assertIsNotNone(parse_datetime("2026-07-20 13:45:00").tzinfo)

    def test_empty_and_garbage_raise(self):
        for text in ("", "   ", "yesterday", "2026-13-45"):
            with self.subTest(text=text):
                with self.assertRaises(RowError):
                    parse_datetime(text)


class UploadViewTests(ImportTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client(HTTP_HOST="localhost")
        self.client.force_login(self.user)

    def post(self, name, content):
        return self.client.post(reverse("import_upload"), {
            "cloud_account": self.accounts["aws"].pk,
            "file": SimpleUploadedFile(name, content),
        })

    def test_upload_imports_and_redirects_to_the_job(self):
        response = self.post("aws.csv", csv_text(AWS_HEADER, aws_row()).encode())
        job = ImportJob.objects.get()
        self.assertRedirects(response, reverse("import_detail", args=[job.pk]))
        self.assertEqual(job.records_imported, 1)

    def test_wrong_extension_is_refused(self):
        response = self.post("aws.exe", b"anything")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Upload a .csv file.")
        self.assertEqual(ImportJob.objects.count(), 0)

    @override_settings(MAX_UPLOAD_BYTES=64)
    def test_oversized_file_is_refused(self):
        response = self.post("aws.csv", csv_text(AWS_HEADER, aws_row()).encode())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "larger than")
        self.assertEqual(ImportJob.objects.count(), 0)

    def test_cannot_upload_into_another_users_account(self):
        other = get_user_model().objects.create_user("bob", password="pw-for-tests-2")
        foreign = CloudAccount.objects.create(
            user=other, provider="aws", account_name="b", account_identifier="b-1",
        )
        response = self.client.post(reverse("import_upload"), {
            "cloud_account": foreign.pk,
            "file": SimpleUploadedFile("aws.csv", csv_text(AWS_HEADER, aws_row()).encode()),
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ImportJob.objects.count(), 0)
        self.assertEqual(BillingRecord.objects.count(), 0)
