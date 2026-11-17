from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from accounts import views as accounts_views
from alerts import views as alerts_views
from analytics import views as analytics_views
from cloud_accounts import views as cloud_views
from estimates import views as estimates_views
from ingestion import views as ingestion_views
from recommendations import views as rec_views
from reports import views as reports_views
from resources import views as resources_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", analytics_views.dashboard, name="dashboard"),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="accounts/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/signup/", accounts_views.signup, name="signup"),
    path("cloud-accounts/", cloud_views.account_list, name="cloud_accounts"),
    path("cloud-accounts/add/", cloud_views.account_add, name="cloud_account_add"),
    path("imports/", ingestion_views.import_list, name="imports"),
    path("imports/upload/", ingestion_views.import_upload, name="import_upload"),
    path("imports/<int:pk>/", ingestion_views.import_detail, name="import_detail"),
    path("resources/", resources_views.resource_list, name="resources"),
    path("resources/import/", resources_views.resource_import, name="resources_import"),
    path("estimates/", estimates_views.estimate_list, name="estimates"),
    path("estimates/upload/", estimates_views.estimate_upload, name="estimate_upload"),
    path("estimates/<int:pk>/", estimates_views.estimate_detail, name="estimate_detail"),
    path("anomalies/", alerts_views.anomaly_list, name="anomalies"),
    path("anomalies/<int:pk>/status/", alerts_views.anomaly_status, name="anomaly_status"),
    path("forecast/", analytics_views.forecast, name="forecast"),
    path("pipeline/run/", analytics_views.pipeline_run, name="pipeline_run"),
    path("recommendations/", rec_views.recommendation_list, name="recommendations"),
    path("recommendations/<int:pk>/status/", rec_views.recommendation_status, name="recommendation_status"),
    path("recommendations/<int:pk>/explain/", rec_views.recommendation_explain, name="recommendation_explain"),
    path("reports/", reports_views.index, name="reports"),
    path("reports/costs.csv", reports_views.costs_csv, name="report_costs_csv"),
    path("reports/anomalies.csv", reports_views.anomalies_csv, name="report_anomalies_csv"),
    path("reports/recommendations.csv", reports_views.recommendations_csv, name="report_recommendations_csv"),
    path("reports/summary/", reports_views.summary, name="report_summary"),
]
