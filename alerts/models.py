from django.conf import settings
from django.db import models

from cloud_accounts.models import PROVIDERS


class CostAnomaly(models.Model):
    STATUS = [
        ("open", "Open"),
        ("acknowledged", "Acknowledged"),
        ("resolved", "Resolved"),
        ("dismissed", "Dismissed"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cost_anomalies")
    provider = models.CharField(max_length=10, choices=PROVIDERS)
    service = models.CharField(max_length=200)
    usage_date = models.DateField()
    observed_cost = models.DecimalField(max_digits=18, decimal_places=2)
    expected_cost = models.DecimalField(max_digits=18, decimal_places=2)
    deviation = models.DecimalField(max_digits=18, decimal_places=2)
    deviation_pct = models.DecimalField(max_digits=12, decimal_places=1, null=True, blank=True)
    currency = models.CharField(max_length=3, default="USD")
    method = models.CharField(max_length=60)
    explanation = models.TextField()
    detected_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS, default="open")

    class Meta:
        ordering = ["-usage_date", "-deviation"]
        constraints = [
            models.UniqueConstraint(fields=["user", "provider", "service", "usage_date"], name="uniq_anomaly_per_day"),
        ]

    def __str__(self):
        return f"{self.provider} {self.service} {self.usage_date}"
