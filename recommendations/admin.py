from django.contrib import admin

from .models import Recommendation


@admin.register(Recommendation)
class RecommendationAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "estimated_savings", "status", "user", "updated_at")
    list_filter = ("category", "status")
