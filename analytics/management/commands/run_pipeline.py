"""Recompute anomalies, the forecast and recommendations.

Scheduled by Kestra (see infra/kestra/). Read-only with respect to any cloud
account: it only reads imported billing rows and writes analysis results.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from analytics.pipeline import run_for_user


class Command(BaseCommand):
    help = "Run anomaly detection, forecasting and recommendations."

    def add_arguments(self, parser):
        parser.add_argument("--username", help="Only run for this user.")

    def handle(self, *args, **options):
        User = get_user_model()
        users = User.objects.filter(billing_records__isnull=False).distinct()
        if options["username"]:
            users = User.objects.filter(username=options["username"])
            if not users.exists():
                raise CommandError(f"No user named '{options['username']}'.")
        count = 0
        for user in users:
            result = run_for_user(user)
            count += 1
            self.stdout.write(
                f"{user.username}: {result['anomalies']} anomalies, "
                f"forecast {result['forecast']['status']}, "
                f"{result['recommendations']} recommendations"
            )
        self.stdout.write(self.style.SUCCESS(f"Pipeline finished for {count} user(s)."))
