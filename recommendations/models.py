from django.conf import settings
from django.db import models


class Recommendation(models.Model):
    """A rule-based suggestion for human review. The app never changes cloud resources itself."""

    STATUS = [
        ("open", "Open"),
        ("accepted", "Accepted"),
        ("rejected", "Rejected"),
        ("implemented", "Implemented"),
    ]
    CATEGORIES = [
        ("idle_resource", "Idle resource"),
        ("unattached_resource", "Unattached resource"),
        ("cost_concentration", "Cost concentration"),
        ("cost_growth", "Cost growth"),
        ("unattributed_spend", "Unattributed spend"),
        ("commitment", "Commitment discount"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recommendations")
    category = models.CharField(max_length=40, choices=CATEGORIES)
    title = models.CharField(max_length=200)
    explanation = models.TextField()
    ai_explanation = models.TextField(blank=True)
    evidence = models.JSONField(default=dict, blank=True)
    # Null unless the saving is directly supported by billing evidence.
    estimated_savings = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default="USD")
    status = models.CharField(max_length=20, choices=STATUS, default="open")
    review_note = models.CharField(max_length=300, blank=True)
    dedupe_key = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-estimated_savings", "category"]
        constraints = [
            models.UniqueConstraint(fields=["user", "dedupe_key"], name="uniq_recommendation_per_user"),
        ]

    def __str__(self):
        return self.title
