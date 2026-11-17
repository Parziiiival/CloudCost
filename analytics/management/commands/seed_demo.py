"""Load the bundled sample data for a demo user.

Everything here is simulated: no cloud account is contacted and nothing is
created in any cloud. The demo password comes from DEMO_USER_PASSWORD so that
no credential lives in the repository.
"""
import os
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from analytics.pipeline import run_for_user
from cloud_accounts.models import CloudAccount
from estimates.models import InfracostEstimate
from estimates.parser import parse_infracost
from ingestion.models import ImportJob
from ingestion.services import run_import
from resources.importer import import_inventory

SAMPLES = Path(settings.BASE_DIR) / "sample_data"
ACCOUNTS = [
    ("aws", "AWS Production (sample)", "111122223333", "aws_billing.csv"),
    ("azure", "Contoso Azure (sample)", "contoso-billing-001", "azure_billing.csv"),
    ("gcp", "Acme GCP (sample)", "01ABCD-234EFG-567HIJ", "gcp_billing.csv"),
]


class Command(BaseCommand):
    help = "Create the demo user and import the sample multi-cloud datasets."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="demo")

    def handle(self, *args, **options):
        password = os.environ.get("DEMO_USER_PASSWORD", "")
        if not password:
            raise CommandError(
                "Set DEMO_USER_PASSWORD (for example in .env) before seeding the demo user."
            )
        User = get_user_model()
        user, created = User.objects.get_or_create(username=options["username"])
        user.set_password(password)
        user.save()
        self.stdout.write(f"{'Created' if created else 'Updated'} user '{user.username}'.")

        for provider, name, identifier, filename in ACCOUNTS:
            account, _ = CloudAccount.objects.get_or_create(
                user=user,
                provider=provider,
                account_identifier=identifier,
                defaults={"account_name": name},
            )
            path = SAMPLES / filename
            if not path.exists():
                raise CommandError(f"Missing {path}. Run sample_data/generate_samples.py first.")
            job = ImportJob.objects.create(user=user, cloud_account=account, source_file=filename)
            with path.open("rb") as handle:
                run_import(job, handle)
            self.stdout.write(
                f"  {filename}: {job.status}, {job.records_imported} imported, "
                f"{job.records_duplicate} duplicate, {job.records_rejected} rejected"
            )

        inventory = SAMPLES / "cloudquery_resources.json"
        if inventory.exists():
            imported, skipped = import_inventory(user, inventory.read_text(encoding="utf-8"))
            self.stdout.write(f"  inventory: {imported} resources, {skipped} skipped")

        infracost = SAMPLES / "infracost_sample.json"
        if infracost.exists() and not InfracostEstimate.objects.filter(user=user).exists():
            parsed = parse_infracost(infracost.read_text(encoding="utf-8"))
            InfracostEstimate.objects.create(
                user=user,
                name="Sample Terraform plan",
                source_file=infracost.name,
                total_monthly_cost=parsed["total"],
                currency=parsed["currency"],
                breakdown=parsed["breakdown"],
            )
            self.stdout.write("  infracost: sample estimate stored")

        result = run_for_user(user)
        self.stdout.write(
            self.style.SUCCESS(
                f"Pipeline: {result['anomalies']} anomalies, forecast {result['forecast']['status']}, "
                f"{result['recommendations']} recommendations."
            )
        )
