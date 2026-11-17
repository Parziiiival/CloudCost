from django.contrib import admin

from .models import InfracostEstimate


@admin.register(InfracostEstimate)
class InfracostEstimateAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "total_monthly_cost", "currency", "created_at")
