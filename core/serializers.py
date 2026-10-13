from rest_framework import serializers
from core.models import Product
from core.models import Dealer
from django.db import transaction
from decimal import Decimal
from core.models import Dealer, Order, OrderItem, Product

class ProductSerializer(serializers.ModelSerializer):
    price = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        coerce_to_string=True,
    )

    class Meta:
        model = Product
        fields = [
            "sku",
            "name",
            "category",
            "brand",
            "vehicle_fitment",
            "price",
            "stock",
            "description",
        ]
        read_only_fields = ["stock"]

    def validate_price(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Price must be greater than zero."
            )
        return value
class DealerSerializer(serializers.ModelSerializer):
    credit_limit = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        coerce_to_string=True,
        required=False,
    )

    class Meta:
        model = Dealer
        fields = [
            "id",
            "dealer_code",
            "name",
            "city",
            "phone",
            "email",
            "gstin",
            "credit_limit",
        ]
        read_only_fields = ["id"]


class OrderItemInputSerializer(serializers.Serializer):
    sku = serializers.CharField()
    quantity = serializers.IntegerField(min_value=1)


class OrderCreateSerializer(serializers.Serializer):
    dealer_id = serializers.IntegerField(min_value=1)
    items = OrderItemInputSerializer(many=True, allow_empty=False)

    def validate(self, attrs):
        skus = [item["sku"] for item in attrs["items"]]

        if len(skus) != len(set(skus)):
            raise serializers.ValidationError(
                {"items": "Duplicate SKUs are not allowed."}
            )

        try:
            attrs["dealer"] = Dealer.objects.get(
                id=attrs["dealer_id"]
            )
        except Dealer.DoesNotExist:
            raise serializers.ValidationError(
                {"dealer_id": "Dealer not found."}
            )

        products = {
            product.sku: product
            for product in Product.objects.filter(sku__in=skus)
        }

        missing_skus = [sku for sku in skus if sku not in products]
        if missing_skus:
            raise serializers.ValidationError(
                {"items": f"Unknown SKU(s): {', '.join(missing_skus)}"}
            )

        attrs["products"] = products
        return attrs

    def create(self, validated_data):
        items_data = validated_data["items"]
        products = validated_data["products"]

        with transaction.atomic():
            order = Order.objects.create(
                dealer=validated_data["dealer"],
                status="DRAFT",
                total_amount=Decimal("0.00"),
            )

            total = Decimal("0.00")

            for item in items_data:
                product = products[item["sku"]]
                quantity = item["quantity"]
                unit_price = product.price
                line_total = unit_price * quantity

                OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=quantity,
                    unit_price=unit_price,
                    line_total=line_total,
                )
                total += line_total

            order.total_amount = total
            order.save(update_fields=["total_amount"])

        return order
