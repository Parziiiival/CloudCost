from django.contrib import admin

from .models import CloudResource


@admin.register(CloudResource)
class CloudResourceAdmin(admin.ModelAdmin):
    list_display = ("resource_name", "provider", "resource_type", "region", "status", "user")
    list_filter = ("provider", "status")
    search_fields = ("resource_id", "resource_name")
