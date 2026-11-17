from django.contrib import admin

from .models import CostForecast


@admin.register(CostForecast)
class CostForecastAdmin(admin.ModelAdmin):
    list_display = ("forecast_period", "user", "predicted_cost", "lower_bound", "upper_bound", "model_name", "created_at")
