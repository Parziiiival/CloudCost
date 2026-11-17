from django.contrib import admin

from .models import CostAnomaly


@admin.register(CostAnomaly)
class CostAnomalyAdmin(admin.ModelAdmin):
    list_display = ("usage_date", "provider", "service", "observed_cost", "expected_cost", "status", "user")
    list_filter = ("provider", "status")
