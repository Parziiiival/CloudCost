from django.conf import settings
from django.db import models

from cloud_accounts.models import PROVIDERS


class CloudResource(models.Model):
    """Read-only resource inventory (e.g. from CloudQuery). Never used to modify cloud resources."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cloud_resources")
    cloud_account = models.ForeignKey(
        "cloud_accounts.CloudAccount", on_delete=models.SET_NULL, null=True, blank=True, related_name="resources"
    )
    provider = models.CharField(max_length=10, choices=PROVIDERS)
    resource_id = models.CharField(max_length=500)
    resource_type = models.CharField(max_length=120, blank=True)
    resource_name = models.CharField(max_length=200, blank=True)
    region = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=60, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    last_seen_at = models.DateTimeField()

    class Meta:
        ordering = ["provider", "resource_type", "resource_name"]
        constraints = [
            models.UniqueConstraint(fields=["user", "provider", "resource_id"], name="uniq_resource_per_user"),
        ]

    def __str__(self):
        return f"{self.provider}:{self.resource_name or self.resource_id}"
