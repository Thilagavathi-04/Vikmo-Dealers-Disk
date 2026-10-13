
import csv
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Dealer, Product


class Command(BaseCommand):
    help = "Load catalogue and dealer CSV data safely and repeatedly."

    def read_csv(self, filename):
        path = Path(settings.DATA_DIR) / filename

        if not path.is_file():
            raise CommandError(f"Required data file not found: {path}")

        with path.open("r", encoding="utf-8-sig", newline="") as file:
            return list(csv.DictReader(file))

    @transaction.atomic
    def handle(self, *args, **options):
        products = self.read_csv("catalogue.csv")
        dealers = self.read_csv("dealers.csv")

        product_rows = {}
        for row in products:
            sku = row["sku"].strip()
            if not sku:
                raise CommandError("Catalogue contains an empty SKU.")

            product_rows[sku] = {
                "name": row["name"].strip(),
                "category": row["category"].strip(),
                "brand": row["brand"].strip(),
                "vehicle_fitment": row["vehicle_fitment"].strip(),
                "price": Decimal(row["price"]),
                "stock": int(row["stock"]),
                "description": row.get("description", "").strip(),
            }

        dealer_rows = {}
        for row in dealers:
            code = row["dealer_code"].strip()
            if not code:
                raise CommandError("Dealers CSV contains an empty dealer code.")

            dealer_rows[code] = {
                "name": row["name"].strip(),
                "city": row.get("city", "").strip(),
                "phone": row.get("phone", "").strip(),
                "email": row.get("email", "").strip(),
                "gstin": row.get("gstin", "").strip(),
                "credit_limit": Decimal(row["credit_limit"]),
            }

        existing_products = {
            obj.sku: obj
            for obj in Product.objects.filter(sku__in=product_rows)
        }
        new_products = []
        changed_products = []

        for sku, defaults in product_rows.items():
            obj = existing_products.get(sku)
            if obj is None:
                new_products.append(Product(sku=sku, **defaults))
                continue

            changed = False
            for field, value in defaults.items():
                if getattr(obj, field) != value:
                    setattr(obj, field, value)
                    changed = True
            if changed:
                changed_products.append(obj)

        if new_products:
            Product.objects.bulk_create(new_products, batch_size=200)
        if changed_products:
            Product.objects.bulk_update(
                changed_products,
                fields=[
                    "name", "category", "brand", "vehicle_fitment",
                    "price", "stock", "description",
                ],
                batch_size=200,
            )

        existing_dealers = {
            obj.dealer_code: obj
            for obj in Dealer.objects.filter(dealer_code__in=dealer_rows)
        }
        new_dealers = []
        changed_dealers = []

        for code, defaults in dealer_rows.items():
            obj = existing_dealers.get(code)
            if obj is None:
                new_dealers.append(Dealer(dealer_code=code, **defaults))
                continue

            changed = False
            for field, value in defaults.items():
                if getattr(obj, field) != value:
                    setattr(obj, field, value)
                    changed = True
            if changed:
                changed_dealers.append(obj)

        if new_dealers:
            Dealer.objects.bulk_create(new_dealers, batch_size=200)
        if changed_dealers:
            Dealer.objects.bulk_update(
                changed_dealers,
                fields=[
                    "name", "city", "phone", "email", "gstin",
                    "credit_limit",
                ],
                batch_size=200,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed complete: {len(new_products)} products created, "
                f"{len(new_dealers)} dealers created; "
                f"{len(changed_products)} products and "
                f"{len(changed_dealers)} dealers updated. "
                f"Totals: {Product.objects.count()} products, "
                f"{Dealer.objects.count()} dealers."
            )
        )
