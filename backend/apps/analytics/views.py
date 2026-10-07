"""Business reports and assistant API (Phase 24). Administrators and store managers; managers see
their own stores only (`?store=` narrows, never widens).

- `GET  /api/admin/reports/`                                  the list of reports
- `GET  /api/admin/reports/{key}/?from=&to=&group_by=&store=` one report (KPIs, series, tables, notes)
- `GET  /api/admin/reports/{key}/export/?table=&from=&to=&store=`  CSV of one table (or `table=kpis`)
- `GET  /api/admin/assistant/`                                status: AI provider, suggestions, reports
- `POST /api/admin/assistant/`                                `{question, store?}` → answer from a report
- `GET  /api/admin/assistant/history/`                        the person's last 30 questions
"""

import csv
import io

from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsStaffRole, managed_store_ids
from apps.dashboard.scope import date_range, store_ids_for
from apps.stores.models import Store
from integrations.llm import get_llm_provider

from . import assistant, reports
from .models import BusinessQuestion

PERIOD_PARAMS = [
    OpenApiParameter("from", str, description="First day (YYYY-MM-DD). Default: 30 days ago"),
    OpenApiParameter("to", str, description="Last day (YYYY-MM-DD). Default: today"),
    OpenApiParameter("store", int, description="One store (managers: one of theirs)"),
]


def _scope(request) -> reports.Scope:
    first, last, start, end = date_range(request)
    period = request.query_params.get("group_by")
    if period not in ("day", "week", "month"):
        days = (last - first).days + 1
        period = "day" if days <= 45 else "week" if days <= 180 else "month"
    return reports.Scope(store_ids_for(request), first, last, start, end, period)


def _report(key: str) -> reports.ReportSpec:
    spec = reports.REPORTS.get(key)
    if spec is None:
        raise NotFound("No such report.")
    return spec


class ReportListView(APIView):
    permission_classes = [IsStaffRole]

    @extend_schema(operation_id="admin_reports_list", responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        return Response(
            {
                "results": [
                    {"key": s.key, "title": s.title, "description": s.description} for s in reports.REPORTS.values()
                ]
            }
        )


class ReportView(APIView):
    permission_classes = [IsStaffRole]

    @extend_schema(
        parameters=[*PERIOD_PARAMS, OpenApiParameter("group_by", str, enum=["day", "week", "month"])],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, key):
        _report(key)
        return Response(reports.build(key, _scope(request)))


def _cell(value) -> str:
    text = "" if value is None else str(value)
    return (
        "'" + text if text[:1] in ("=", "+", "-", "@") and not text.lstrip("-").replace(".", "", 1).isdigit() else text
    )


class ReportExportView(APIView):
    """CSV for a spreadsheet. Text that could run as a spreadsheet formula is prefixed with '."""

    permission_classes = [IsStaffRole]

    @extend_schema(
        parameters=[*PERIOD_PARAMS, OpenApiParameter("table", str, description="Table key, or 'kpis'")],
        responses={(200, "text/csv"): OpenApiTypes.STR},
    )
    def get(self, request, key):
        _report(key)
        scope = _scope(request)
        data = reports.build(key, scope)
        wanted = request.query_params.get("table") or (data["tables"][0]["key"] if data["tables"] else "kpis")
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([f"{data['title']} · {scope.first.isoformat()} to {scope.last.isoformat()}"])
        if wanted == "kpis":
            writer.writerow(["Measure", "Value"])
            for row in data["kpis"]:
                writer.writerow([_cell(row["label"]), _cell(row["value"])])
        else:
            table = next((t for t in data["tables"] if t["key"] == wanted), None)
            if table is None:
                raise NotFound("No such table in this report.")
            writer.writerow([c["label"] for c in table["columns"]])
            for row in table["rows"]:
                writer.writerow([_cell(row.get(c["key"])) for c in table["columns"]])
        response = HttpResponse("﻿" + buffer.getvalue(), content_type="text/csv; charset=utf-8")
        filename = f"{key}-{wanted}-{scope.first.isoformat()}-{scope.last.isoformat()}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class BusinessAskSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=assistant.MAX_QUESTION, trim_whitespace=True)


def _visible_stores(request) -> list[tuple[int, str]]:
    allowed = managed_store_ids(request.user)
    stores = Store.objects.all() if allowed is None else Store.objects.filter(pk__in=allowed)
    return list(stores.order_by("name").values_list("pk", "name"))


class BusinessAssistantView(APIView):
    permission_classes = [IsStaffRole]
    throttle_scope = "ai"

    def get_throttles(self):
        from rest_framework.throttling import ScopedRateThrottle

        return [ScopedRateThrottle()] if self.request.method == "POST" else []

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        provider = get_llm_provider()
        return Response(
            {
                "ai": {"provider": provider.name, "model": provider.model, "available": provider.available},
                "suggestions": assistant.SUGGESTIONS,
                "topics": [{"key": i.key, "label": i.label, "report": i.report} for i in assistant.INTENTS],
                "stores": [{"id": pk, "name": name} for pk, name in _visible_stores(request)],
            }
        )

    @extend_schema(request=BusinessAskSerializer, parameters=[PERIOD_PARAMS[2]], responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        serializer = BusinessAskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = assistant.answer(
            serializer.validated_data["question"], store_ids=store_ids_for(request), stores=_visible_stores(request)
        )
        BusinessQuestion.objects.create(
            user=request.user,
            question=result["question"],
            intent=result.get("intent") or "",
            report=result.get("report") or "",
            period_from=(result.get("period") or {}).get("from"),
            period_to=(result.get("period") or {}).get("to"),
            store_name=result.get("store") or "",
            answer=result["text"][:2000],
            source=result.get("source", "rules"),
        )
        return Response(result)


class AssistantHistoryView(APIView):
    permission_classes = [IsStaffRole]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        rows = BusinessQuestion.objects.filter(user=request.user)[:30]
        return Response(
            {
                "results": [
                    {
                        "id": r.id,
                        "question": r.question,
                        "answer": r.answer,
                        "report": r.report,
                        "period": {"from": r.period_from, "to": r.period_to},
                        "store": r.store_name or None,
                        "source": r.source,
                        "created_at": r.created_at,
                    }
                    for r in rows
                ]
            }
        )
