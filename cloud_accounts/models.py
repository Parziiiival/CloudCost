from django.conf import settings
from django.db import models

PROVIDERS = [("aws", "AWS"), ("azure", "Azure"), ("gcp", "GCP")]
PROVIDER_LABELS = dict(PROVIDERS)


class CloudAccount(models.Model):
    STATUS = [
        ("csv_import", "CSV import (no live connection)"),
        ("connected", "Connected (read-only)"),
        ("error", "Connection error"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cloud_accounts")
    provider = models.CharField(max_length=10, choices=PROVIDERS)
    account_name = models.CharField(max_length=120)
    account_identifier = models.CharField(
        max_length=200, help_text="AWS account ID, Azure subscription, or GCP billing account/project."
    )
    connection_status = models.CharField(max_length=20, choices=STATUS, default="csv_import")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["provider", "account_name"]
        constraints = [
            models.UniqueConstraint(fields=["user", "provider", "account_identifier"], name="uniq_cloud_account"),
        ]

    def __str__(self):
        return f"{self.get_provider_display()} - {self.account_name}"
