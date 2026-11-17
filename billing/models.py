from django.conf import settings
from django.db import models
from django.utils import timezone

from cloud_accounts.models import PROVIDERS


class ExchangeRate(models.Model):
    """Static, illustrative conversion rates to USD. Edit in the admin; not a live FX feed."""

    currency = models.CharField(max_length=3, unique=True)
    rate_to_usd = models.DecimalField(max_digits=18, decimal_places=8)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["currency"]

    def __str__(self):
        return f"1 {self.currency} = {self.rate_to_usd} USD"


class BillingRecord(models.Model):
    """One normalized billing line in the common schema shared by all providers."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="billing_records")
    cloud_account = models.ForeignKey("cloud_accounts.CloudAccount", on_delete=models.CASCADE, related_name="billing_records")
    import_job = models.ForeignKey("ingestion.ImportJob", on_delete=models.CASCADE, related_name="billing_records")
    provider = models.CharField(max_length=10, choices=PROVIDERS)
    billing_account = models.CharField(max_length=200, blank=True)
    project_or_subscription = models.CharField(max_length=200, blank=True)
    service = models.CharField(max_length=200)
    resource_id = models.CharField(max_length=500, blank=True)
    region = models.CharField(max_length=100, blank=True)
    usage_start = models.DateTimeField()
    usage_end = models.DateTimeField()
    usage_quantity = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    usage_unit = models.CharField(max_length=60, blank=True)
    cost = models.DecimalField(max_digits=18, decimal_places=6)
    currency = models.CharField(max_length=3, default="USD")
    import_timestamp = models.DateTimeField(default=timezone.now)
    record_hash = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "record_hash"], name="uniq_billing_record_per_user"),
        ]
        indexes = [
            models.Index(fields=["user", "usage_start"]),
            models.Index(fields=["user", "provider"]),
        ]

    def __str__(self):
        return f"{self.provider} {self.service} {self.usage_start:%Y-%m-%d} {self.cost} {self.currency}"
