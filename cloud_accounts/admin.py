from django.contrib import admin

from .models import CloudAccount


@admin.register(CloudAccount)
class CloudAccountAdmin(admin.ModelAdmin):
    list_display = ("account_name", "provider", "account_identifier", "user", "connection_status", "created_at")
    list_filter = ("provider", "connection_status")
    search_fields = ("account_name", "account_identifier")
