"""The analysis pipeline: anomalies, forecast and recommendations for one user.

Run after an import, from the dashboard button, or on a schedule (Kestra runs
`python manage.py run_pipeline`). It only reads billing data and writes
analysis results to this app's own database.
"""
import logging

from alerts.detection import detect_for_user
from recommendations.rules import generate_for_user

from .forecasting import run_forecast

logger = logging.getLogger(__name__)


def run_for_user(user):
    anomalies = detect_for_user(user)
    forecast = run_forecast(user)
    recommendations = generate_for_user(user)
    logger.info(
        "pipeline for user %s: anomalies=%s forecast=%s recommendations=%s",
        user.pk, anomalies, forecast["status"], recommendations,
    )
    return {"anomalies": anomalies, "forecast": forecast, "recommendations": recommendations}
