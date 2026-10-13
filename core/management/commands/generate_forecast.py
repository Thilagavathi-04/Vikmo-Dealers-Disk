
import csv
import math
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import stdev

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


FORECAST_WEEKS = [
    date(2026, 9, 28),
    date(2026, 10, 5),
    date(2026, 10, 12),
    date(2026, 10, 19),
]


class Command(BaseCommand):
    help = "Generate four weeks of SKU-level demand forecasts."

    def handle(self, *args, **options):
        data_dir = Path(settings.BASE_DIR) / "data"
        output_path = Path(settings.BASE_DIR) / "ml" / "forecast.csv"

        lead_times_path = data_dir / "lead_times.csv"
        sales_path = data_dir / "sales_history.csv"

        if not lead_times_path.exists() or not sales_path.exists():
            raise CommandError("Required forecasting input CSV is missing.")

        lead_times = {}
        with lead_times_path.open(newline="", encoding="utf-8-sig") as file:
            for row in csv.DictReader(file):
                sku = row["sku"].strip()
                lead_time = int(row["lead_time_weeks"])
                if not sku or lead_time < 1:
                    raise CommandError(f"Invalid lead-time record: {row}")
                lead_times[sku] = lead_time

        sales_by_sku = defaultdict(list)
        with sales_path.open(newline="", encoding="utf-8-sig") as file:
            for row in csv.DictReader(file):
                sku = row["sku"].strip()
                units = int(row["units_sold"])
                week = date.fromisoformat(row["week_start"])
                if units < 0:
                    raise CommandError(f"Negative sales found: {row}")
                sales_by_sku[sku].append((week, units))

        if len(lead_times) != 40:
            raise CommandError(
                f"Expected 40 SKUs in lead_times.csv, found {len(lead_times)}."
            )

        forecasts = []
        for sku in sorted(lead_times):
            history = sorted(sales_by_sku.get(sku, []))
            if not history:
                raise CommandError(f"No sales history found for {sku}.")

            recent_units = [units for _, units in history[-12:]]
            baseline = sum(recent_units) / len(recent_units)

            # Retain the simple baseline forecast for all four weeks.
            forecast_units = max(0, round(baseline))

            for week in FORECAST_WEEKS:
                forecasts.append({
                    "sku": sku,
                    "week_start": week.isoformat(),
                    "forecast_units": forecast_units,
                })

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=["sku", "week_start", "forecast_units"],
            )
            writer.writeheader()
            writer.writerows(forecasts)

        self.stdout.write(
            self.style.SUCCESS(
                f"Generated {len(forecasts)} forecast rows at {output_path}"
            )
        )
