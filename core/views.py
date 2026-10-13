
import logging
import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse

from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from core.models import Dealer, Order, OrderItem, Product
from core.serializers import (
    DealerSerializer,
    OrderCreateSerializer,
    ProductSerializer,
)
from core.services.ai_assistant import chat_with_assistant
from core.services.forecasting import (
    calculate_reorder,
    load_forecasts,
    load_lead_times,
    load_sales_history,
)

logger = logging.getLogger(__name__)

TAX_RATE = Decimal("0.18")


def api_error(code, message, http_status, details=None):
    """Return errors in the API contract's standard format."""
    if details is None:
        details = []
    elif isinstance(details, dict):
        flattened = []

        def flatten(value):
            if isinstance(value, dict):
                for nested in value.values():
                    flatten(nested)
            elif isinstance(value, (list, tuple)):
                for nested in value:
                    flatten(nested)
            else:
                flattened.append(str(value))

        flatten(details)
        details = flattened

    return Response(
        {
            "error": {
                "code": code,
                "message": message,
                "details": details,
            }
        },
        status=http_status,
    )


class ProductPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def money(value):
    """Format a monetary amount as a two-decimal JSON string."""
    return f"{value:.2f}"


def calculate_tax(subtotal):
    return (subtotal * TAX_RATE).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def health(request):
    return JsonResponse({"status": "ok"})


@api_view(["GET", "POST"])
def products(request):
    if request.method == "GET":
        queryset = Product.objects.all()

        search = request.query_params.get("search", "").strip()
        category = request.query_params.get("category", "").strip()
        vehicle = request.query_params.get("vehicle", "").strip()

        if search:
            queryset = queryset.filter(
                Q(sku__icontains=search)
                | Q(name__icontains=search)
                | Q(brand__icontains=search)
            )

        if category:
            queryset = queryset.filter(category__iexact=category)

        if vehicle:
            queryset = queryset.filter(
                vehicle_fitment__icontains=vehicle
            )

        paginator = ProductPagination()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(
            ProductSerializer(page, many=True).data
        )

    serializer = ProductSerializer(data=request.data)

    if not serializer.is_valid():
        return api_error(
            "VALIDATION_ERROR",
            "Invalid product data.",
            status.HTTP_400_BAD_REQUEST,
            serializer.errors,
        )

    try:
        with transaction.atomic():
            product = serializer.save(stock=0)
    except IntegrityError:
        return api_error(
            "DUPLICATE",
            "A product with this SKU already exists.",
            status.HTTP_409_CONFLICT,
        )

    return Response(
        ProductSerializer(product).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET", "PATCH"])
def product_detail(request, sku):
    try:
        product = Product.objects.get(sku=sku)
    except Product.DoesNotExist:
        return api_error(
            "NOT_FOUND",
            "Product not found.",
            status.HTTP_404_NOT_FOUND,
        )

    if request.method == "GET":
        return Response(ProductSerializer(product).data)

    if "sku" in request.data:
        return api_error(
            "VALIDATION_ERROR",
            "SKU cannot be changed.",
            status.HTTP_400_BAD_REQUEST,
        )

    serializer = ProductSerializer(
        product,
        data=request.data,
        partial=True,
    )

    if not serializer.is_valid():
        return api_error(
            "VALIDATION_ERROR",
            "Invalid product data.",
            status.HTTP_400_BAD_REQUEST,
            serializer.errors,
        )

    serializer.save()
    return Response(ProductSerializer(product).data)


@api_view(["PUT"])
def inventory_update(request, sku):
    try:
        product = Product.objects.get(sku=sku)
    except Product.DoesNotExist:
        return api_error(
            "NOT_FOUND",
            "Product not found.",
            status.HTTP_404_NOT_FOUND,
        )

    quantity = request.data.get("quantity")
    reason = request.data.get("reason")

    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or quantity < 0
    ):
        return api_error(
            "VALIDATION_ERROR",
            "Quantity must be an integer greater than or equal to zero.",
            status.HTTP_400_BAD_REQUEST,
        )

    if not isinstance(reason, str) or not reason.strip():
        return api_error(
            "VALIDATION_ERROR",
            "A non-empty reason is required.",
            status.HTTP_400_BAD_REQUEST,
        )

    product.stock = quantity
    product.save(update_fields=["stock"])

    return Response({
        "sku": product.sku,
        "quantity": product.stock,
    })


@api_view(["GET", "POST"])
def dealers(request):
    if request.method == "GET":
        queryset = Dealer.objects.all()
        paginator = ProductPagination()
        page = paginator.paginate_queryset(queryset, request)

        return paginator.get_paginated_response(
            DealerSerializer(page, many=True).data
        )

    serializer = DealerSerializer(data=request.data)

    if not serializer.is_valid():
        return api_error(
            "VALIDATION_ERROR",
            "Invalid dealer data.",
            status.HTTP_400_BAD_REQUEST,
            serializer.errors,
        )

    try:
        with transaction.atomic():
            dealer = serializer.save()
    except IntegrityError:
        return api_error(
            "DUPLICATE",
            "A dealer with this dealer code already exists.",
            status.HTTP_409_CONFLICT,
        )

    return Response(
        DealerSerializer(dealer).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
def dealer_detail(request, dealer_id):
    try:
        dealer = Dealer.objects.get(id=dealer_id)
    except Dealer.DoesNotExist:
        return api_error(
            "NOT_FOUND",
            "Dealer not found.",
            status.HTTP_404_NOT_FOUND,
        )

    return Response(DealerSerializer(dealer).data)


class OrderItemOutputSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(source="product.sku", read_only=True)
    name = serializers.CharField(source="product.name", read_only=True)
    line_subtotal = serializers.SerializerMethodField()
    line_tax = serializers.SerializerMethodField()
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            "sku",
            "name",
            "quantity",
            "unit_price",
            "line_subtotal",
            "line_tax",
            "line_total",
        ]

    def get_line_subtotal(self, obj):
        return money(obj.unit_price * obj.quantity)

    def get_line_tax(self, obj):
        subtotal = obj.unit_price * obj.quantity
        return money(calculate_tax(subtotal))

    def get_line_total(self, obj):
        subtotal = obj.unit_price * obj.quantity
        return money(subtotal + calculate_tax(subtotal))


class OrderOutputSerializer(serializers.ModelSerializer):
    dealer_id = serializers.IntegerField(
        source="dealer.id",
        read_only=True,
    )
    items = OrderItemOutputSerializer(many=True, read_only=True)
    subtotal = serializers.SerializerMethodField()
    tax_total = serializers.SerializerMethodField()
    grand_total = serializers.SerializerMethodField()
    updated_at = serializers.DateTimeField(
        source="created_at",
        read_only=True,
    )

    class Meta:
        model = Order
        fields = [
            "order_number",
            "dealer_id",
            "status",
            "items",
            "subtotal",
            "tax_total",
            "grand_total",
            "created_at",
            "updated_at",
        ]

    def _totals(self, obj):
        subtotal = Decimal("0.00")
        tax_total = Decimal("0.00")

        for item in obj.items.all():
            line_subtotal = item.unit_price * item.quantity
            subtotal += line_subtotal
            tax_total += calculate_tax(line_subtotal)

        return subtotal, tax_total

    def get_subtotal(self, obj):
        subtotal, _ = self._totals(obj)
        return money(subtotal)

    def get_tax_total(self, obj):
        _, tax_total = self._totals(obj)
        return money(tax_total)

    def get_grand_total(self, obj):
        subtotal, tax_total = self._totals(obj)
        return money(subtotal + tax_total)


@api_view(["GET", "POST"])
def orders(request):
    if request.method == "POST":
        serializer = OrderCreateSerializer(data=request.data)

        if not serializer.is_valid():
            return api_error(
                "VALIDATION_ERROR",
                "Invalid order data.",
                status.HTTP_400_BAD_REQUEST,
                serializer.errors,
            )

        try:
            order = serializer.save()
        except IntegrityError:
            return api_error(
                "DUPLICATE",
                "The order could not be created because of a conflict.",
                status.HTTP_409_CONFLICT,
            )

        return Response(
            OrderOutputSerializer(order).data,
            status=status.HTTP_201_CREATED,
        )

    queryset = (
        Order.objects.select_related("dealer")
        .prefetch_related("items__product")
    )

    dealer_id = request.query_params.get("dealer_id")
    order_status = request.query_params.get("status")

    if dealer_id:
        if not dealer_id.isdigit() or int(dealer_id) < 1:
            return api_error(
                "VALIDATION_ERROR",
                "dealer_id must be a positive integer.",
                status.HTTP_400_BAD_REQUEST,
            )

        queryset = queryset.filter(dealer_id=int(dealer_id))

    if order_status:
        queryset = queryset.filter(status=order_status.upper())

    paginator = ProductPagination()
    page = paginator.paginate_queryset(queryset, request)

    return paginator.get_paginated_response(
        OrderOutputSerializer(page, many=True).data
    )


@api_view(["GET"])
def order_detail(request, order_number):
    try:
        order = (
            Order.objects.select_related("dealer")
            .prefetch_related("items__product")
            .get(order_number=order_number)
        )
    except Order.DoesNotExist:
        return api_error(
            "NOT_FOUND",
            "Order not found.",
            status.HTTP_404_NOT_FOUND,
        )

    return Response(OrderOutputSerializer(order).data)


@api_view(["POST"])
def assistant_chat(request):
    message = request.data.get("message")
    session_id = request.data.get("session_id")
    dealer_id = request.data.get("dealer_id")

    if not isinstance(message, str) or not message.strip():
        return api_error(
            "VALIDATION_ERROR",
            "message must be a non-empty string.",
            status.HTTP_400_BAD_REQUEST,
        )

    if session_id is None:
        session_id = str(uuid.uuid4())
    elif (
        not isinstance(session_id, str)
        or not session_id.strip()
        or len(session_id) > 100
    ):
        return api_error(
            "VALIDATION_ERROR",
            "session_id must be a non-empty string of at most 100 characters.",
            status.HTTP_400_BAD_REQUEST,
        )

    try:
        answer = chat_with_assistant(
            message=message.strip(),
            session_id=session_id,
            dealer_id=dealer_id,
        )
    except RuntimeError:
        logger.exception("Assistant service configuration or runtime error")
        return api_error(
            "AI_SERVICE_ERROR",
            "The assistant is not configured or could not complete the request.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except Exception:
        logger.exception("Unexpected assistant service error")
        return api_error(
            "AI_SERVICE_ERROR",
            "The assistant encountered an unexpected error.",
            status.HTTP_502_BAD_GATEWAY,
        )

    # Support either a plain-text answer or a structured service response.
    if isinstance(answer, dict):
        reply = answer.get("reply") or answer.get("response") or answer.get("message") or ""
        cited_skus = answer.get("cited_skus", [])
        tool_calls = answer.get("tool_calls", [])
        actions = answer.get("actions", [])
    else:
        reply = str(answer)
        cited_skus = []
        tool_calls = []
        actions = []

    return Response({
        "session_id": session_id,
        "reply": str(reply),
        "cited_skus": cited_skus,
        "tool_calls": tool_calls,
        "actions": actions,
    })


@api_view(["GET"])
def forecast_detail(request, sku):
    try:
        product = Product.objects.get(sku__iexact=sku)
    except Product.DoesNotExist:
        return api_error(
            "NOT_FOUND",
            "Product not found.",
            status.HTTP_404_NOT_FOUND,
        )

    forecasts = load_forecasts()
    lead_times = load_lead_times()

    if product.sku not in forecasts or product.sku not in lead_times:
        return api_error(
            "NOT_FOUND",
            "Forecast data not found for this SKU.",
            status.HTTP_404_NOT_FOUND,
        )

    sales_history = load_sales_history()

    result = calculate_reorder(
        product,
        forecasts,
        lead_times,
        sales_history,
    )

    if result is None:
        return api_error(
            "NOT_FOUND",
            "Forecast data not found for this SKU.",
            status.HTTP_404_NOT_FOUND,
        )

    result["forecast"] = forecasts[product.sku]
    return Response(result)


@api_view(["GET"])
def reorder_suggestions(request):
    forecasts = load_forecasts()
    lead_times = load_lead_times()
    sales_history = load_sales_history()

    suggestions = []

    for product in Product.objects.all().order_by("sku"):
        result = calculate_reorder(
            product,
            forecasts,
            lead_times,
            sales_history,
        )

        if result is not None:
            suggestions.append(result)

    return Response({
        "count": len(suggestions),
        "results": suggestions,
    })
