from django.urls import path

from .views import AssistantHistoryView, BusinessAssistantView, ReportExportView, ReportListView, ReportView

urlpatterns = [
    path("admin/reports/", ReportListView.as_view(), name="admin-reports"),
    path("admin/reports/<str:key>/", ReportView.as_view(), name="admin-report"),
    path("admin/reports/<str:key>/export/", ReportExportView.as_view(), name="admin-report-export"),
    path("admin/assistant/", BusinessAssistantView.as_view(), name="admin-business-assistant"),
    path("admin/assistant/history/", AssistantHistoryView.as_view(), name="admin-business-assistant-history"),
]
