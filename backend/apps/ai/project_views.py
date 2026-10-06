"""Project builder API (Phase 19).

- `GET    /api/ai/project-types/`                     the guided project types (public)
- `GET    /api/ai/projects/`                          the signed-in customer's own projects
- `POST   /api/ai/projects/`                          start one from a description and/or a type (+ answers)
- `GET    /api/ai/projects/{id}/?postal_code=|address_id=`  questions, assumptions, safety and the kit,
                                                      priced as one cart with stock and delivery checked
- `PATCH  /api/ai/projects/{id}/`                     answers / language / title → the kit is worked out again
- `DELETE /api/ai/projects/{id}/`
- `POST   /api/ai/projects/{id}/items/`               add a product of the customer's own choice
- `PATCH  /api/ai/projects/{id}/items/{item_id}/`     change product/variant, quantity, ticked
- `DELETE /api/ai/projects/{id}/items/{item_id}/`     remove a product the customer added
- `POST   /api/ai/projects/{id}/reset/`               back to the suggested lines
- `POST   /api/ai/projects/{id}/add-to-cart/`         every ticked line into the cart, or nothing

Projects belong to their customer (someone else's id gives 404). Prices are never stored: every read
prices the kit again from the database, and the cart prices it again when lines are added.
"""

from django.db.models import Count, Q
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.exceptions import NotFoundError

from .models import Project, ProjectItem
from .projects import builder, kit
from .projects.builder import MAX_DESCRIPTION
from .projects.templates import ALL_TEMPLATES, TEMPLATES
from .views import product_cards


def location_params(request) -> dict:
    """The PIN / saved address to check delivery for, from the query string or the body."""
    source = {**request.query_params.dict(), **(request.data if isinstance(request.data, dict) else {})}
    pin = str(source.get("postal_code") or "").strip()
    raw_address = source.get("address_id")
    address_id = int(raw_address) if str(raw_address or "").isdigit() else None
    return {"postal_code": pin if len(pin) == 6 and pin.isdigit() else "", "address_id": address_id}


def attach_cards(kit_data: dict | None, request) -> None:
    """Product cards (live catalogue rows) for each kit line and its alternatives."""
    if not kit_data:
        return
    context = {"request": request}
    refs = [
        {"product_id": item["product_id"], "variant_id": item["variant"]["id"], "reason": ""}
        for item in kit_data["items"]
        if item["product_id"]
    ]
    cards = {card["id"]: card for card in product_cards(refs, context)}
    alt_ids = sorted({pid for item in kit_data["items"] for pid in item["alternatives"]} - set(cards))
    alt_cards = {card["id"]: card for card in product_cards([{"product_id": pid} for pid in alt_ids], context)}
    for item in kit_data["items"]:
        item["product"] = cards.get(item["product_id"])
        item["alternatives"] = [
            card for pid in item["alternatives"] if (card := alt_cards.get(pid) or cards.get(pid)) is not None
        ]
    problems = kit_data.get("compatibility") or []
    option_ids = {o["product_id"] for problem in problems for o in problem.get("options", [])}
    option_cards = {
        card["id"]: card for card in product_cards([{"product_id": pid} for pid in sorted(option_ids)], context)
    }
    for problem in problems:
        for option in problem.get("options", []):
            option["product"] = option_cards.get(option["product_id"])
        problem["options"] = [o for o in problem.get("options", []) if o.get("product")]


class ProjectStartSerializer(serializers.Serializer):
    description = serializers.CharField(
        max_length=MAX_DESCRIPTION, required=False, allow_blank=True, trim_whitespace=True
    )
    project_type = serializers.ChoiceField(choices=list(TEMPLATES), required=False)
    answers = serializers.DictField(required=False)
    language = serializers.ChoiceField(choices=["en", "hi", "hinglish"], required=False)

    def validate(self, attrs):
        if not attrs.get("description") and not attrs.get("project_type"):
            raise serializers.ValidationError("Describe the job or choose a project type.")
        return attrs


class UpdateSerializer(serializers.Serializer):
    answers = serializers.DictField(required=False)
    language = serializers.ChoiceField(choices=["en", "hi", "hinglish"], required=False)
    title = serializers.CharField(max_length=150, required=False, allow_blank=True)


class ItemChangeSerializer(serializers.Serializer):
    variant_id = serializers.IntegerField(min_value=1, required=False)
    quantity = serializers.IntegerField(min_value=1, max_value=9999, required=False)
    included = serializers.BooleanField(required=False)


class ItemAddSerializer(serializers.Serializer):
    variant_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=9999, default=1)


class ProjectListSerializer(serializers.ModelSerializer):
    item_count = serializers.IntegerField(read_only=True, default=0)
    type_name = serializers.CharField(source="get_project_type_display", read_only=True)

    class Meta:
        model = Project
        fields = ["id", "title", "project_type", "type_name", "status", "item_count", "created_at", "updated_at"]


LOCATION_PARAMS = [
    OpenApiParameter("postal_code", str, description="6-digit PIN for the delivery check"),
    OpenApiParameter("address_id", int, description="One of the customer's saved addresses"),
]


class ProjectTypesView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(parameters=[OpenApiParameter("language", str)], responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        language = request.query_params.get("language", "en")
        return Response(
            {"results": builder.templates_payload(language if language in ("en", "hi", "hinglish") else "en")}
        )


class ProjectViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    permission_classes = [IsAuthenticated]
    serializer_class = ProjectListSerializer
    throttle_scope = "ai"

    def get_throttles(self):
        # Reading a plan is cheap; starting and re-working one runs the catalogue search for every material.
        if self.action in ("create", "partial_update", "reset"):
            return [ScopedRateThrottle()]
        return []

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Project.objects.none()
        qs = Project.objects.filter(user=self.request.user, project_type__in=list(ALL_TEMPLATES))
        if self.action == "list":
            qs = qs.annotate(item_count=Count("items", filter=Q(items__included=True)))
        return qs.order_by("-updated_at", "-id")

    def _plan(self, request, project, http_status=status.HTTP_200_OK, **extra):
        data = builder.plan_payload(project, user=request.user, **location_params(request))
        attach_cards(data["kit"], request)
        data.update(extra)
        return Response(data, status=http_status)

    @extend_schema(request=ProjectStartSerializer, responses={201: OpenApiTypes.OBJECT})
    def create(self, request):
        serializer = ProjectStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project = builder.start(request.user, **serializer.validated_data)
        return self._plan(request, project, status.HTTP_201_CREATED)

    @extend_schema(parameters=LOCATION_PARAMS, responses={200: OpenApiTypes.OBJECT})
    def retrieve(self, request, pk=None):
        return self._plan(request, self.get_object())

    @extend_schema(request=UpdateSerializer, responses={200: OpenApiTypes.OBJECT})
    def partial_update(self, request, pk=None):
        serializer = UpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project = builder.answer(self.get_object(), **serializer.validated_data)
        return self._plan(request, project)

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def reset(self, request, pk=None):
        return self._plan(request, builder.reset_suggestions(self.get_object()))

    @extend_schema(request=ItemAddSerializer, responses={201: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"], url_path="items")
    def add_item(self, request, pk=None):
        project = self.get_object()
        serializer = ItemAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        kit.add_extra(project, **serializer.validated_data)
        return self._plan(request, project, status.HTTP_201_CREATED)

    @extend_schema(methods=["patch"], request=ItemChangeSerializer, responses={200: OpenApiTypes.OBJECT})
    @extend_schema(methods=["delete"], request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["patch", "delete"], url_path=r"items/(?P<item_id>\d+)")
    def item(self, request, pk=None, item_id=None):
        project = self.get_object()
        item = ProjectItem.objects.filter(project=project, pk=item_id).first()
        if item is None:
            raise NotFoundError("Item not found.")
        if request.method == "DELETE":
            if not item.material_key.startswith("extra-"):
                raise kit.KitError("Suggested items can be unticked, not removed.", code="suggested_item")
            item.delete()
            return self._plan(request, project)
        serializer = ItemChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        kit.change_item(item, **serializer.validated_data)
        return self._plan(request, project)

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"], url_path="add-to-cart")
    def add_to_cart(self, request, pk=None):
        project = self.get_object()
        result = kit.add_to_cart(project, user=request.user)
        project.refresh_from_db()
        return self._plan(request, project, added=result)
