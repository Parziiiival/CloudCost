from django.conf import settings
from django.db import models


class InfracostEstimate(models.Model):
    """A pre-deployment Terraform cost ESTIMATE from Infracost. Never mixed into actual billing totals."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="infracost_estimates")
    name = models.CharField(max_length=120)
    source_file = models.CharField(max_length=255)
    total_monthly_cost = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    currency = models.CharField(max_length=3, default="USD")
    breakdown = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.name
