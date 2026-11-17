from django.conf import settings
from django.db import models


class CostForecast(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cost_forecasts")
    forecast_period = models.CharField(max_length=40)  # "YYYY-MM-DD to YYYY-MM-DD"
    predicted_cost = models.DecimalField(max_digits=18, decimal_places=2)
    lower_bound = models.DecimalField(max_digits=18, decimal_places=2)
    upper_bound = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    model_name = models.CharField(max_length=60)
    daily = models.JSONField(default=list, blank=True)  # [{"date", "predicted", "lower", "upper"}]
    history_days = models.PositiveIntegerField(default=0)
    backtest_mae = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "forecast_period"], name="uniq_forecast_period_per_user"),
        ]

    def __str__(self):
        return f"{self.forecast_period}: {self.predicted_cost} {self.currency} ({self.model_name})"
