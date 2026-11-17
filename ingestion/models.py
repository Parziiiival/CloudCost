from django.conf import settings
from django.db import models


class ImportJob(models.Model):
    PENDING, RUNNING, COMPLETED, COMPLETED_WITH_ERRORS, FAILED = (
        "pending", "running", "completed", "completed_with_errors", "failed",
    )
    STATUS = [
        (PENDING, "Pending"),
        (RUNNING, "Running"),
        (COMPLETED, "Completed"),
        (COMPLETED_WITH_ERRORS, "Completed with errors"),
        (FAILED, "Failed"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="import_jobs")
    cloud_account = models.ForeignKey("cloud_accounts.CloudAccount", on_delete=models.CASCADE, related_name="import_jobs")
    source_file = models.CharField(max_length=255)
    status = models.CharField(max_length=30, choices=STATUS, default=PENDING)
    records_imported = models.PositiveIntegerField(default=0)
    records_rejected = models.PositiveIntegerField(default=0)
    records_duplicate = models.PositiveIntegerField(default=0)
    error_log = models.JSONField(default=list, blank=True)  # capped list of {"row": n, "reason": "..."}
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Import #{self.pk} {self.source_file} ({self.status})"
