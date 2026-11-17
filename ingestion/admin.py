from django.contrib import admin

from .models import ImportJob


@admin.register(ImportJob)
class ImportJobAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "cloud_account", "source_file", "status", "records_imported", "records_rejected", "created_at")
    list_filter = ("status",)
