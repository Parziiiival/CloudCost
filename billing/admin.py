from django.contrib import admin

from .models import BillingRecord, ExchangeRate


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ("currency", "rate_to_usd", "updated_at")


@admin.register(BillingRecord)
class BillingRecordAdmin(admin.ModelAdmin):
    list_display = ("usage_start", "provider", "service", "resource_id", "cost", "currency", "user")
    list_filter = ("provider", "currency")
    search_fields = ("service", "resource_id")
    date_hierarchy = "usage_start"
