
import csv
import math
from collections import defaultdict
from pathlib import Path
from statistics import stdev

from django.conf import settings


def load_forecasts():
    path = Path(settings.BASE_DIR) / "ml" / "forecast.csv"
    forecasts = defaultdict(list)

    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            forecasts[row["sku"]].append({
                "week_start": row["week_start"],
                "forecast_units": int(row["forecast_units"]),
            })

    for sku in forecasts:
        forecasts[sku].sort(key=lambda item: item["week_start"])

    return dict(forecasts)


def load_lead_times():
    path = Path(settings.BASE_DIR) / "data" / "lead_times.csv"
    lead_times = {}

    with path.open(newline="", encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            lead_times[row["sku"]] = int(row["lead_time_weeks"])

    return lead_times


def load_sales_history():
    path = Path(settings.BASE_DIR) / "data" / "sales_history.csv"
    sales = defaultdict(list)

    with path.open(newline="", encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            sales[row["sku"]].append(
                (row["week_start"], int(row["units_sold"]))
            )

    for sku in sales:
        sales[sku].sort(key=lambda item: item[0])

    return dict(sales)


def calculate_reorder(product, forecasts, lead_times, sales_history):
    sku = product.sku

    if sku not in lead_times or not forecasts.get(sku):
        return None

    lead_time = lead_times[sku]
    future_forecasts = forecasts[sku][:lead_time]

    lead_time_demand = sum(
        item["forecast_units"] for item in future_forecasts
    )

    history = sales_history.get(sku, [])
    recent_sales = [units for _, units in history[-12:]]

    sigma = stdev(recent_sales) if len(recent_sales) >= 2 else 0.0
    safety_stock = math.ceil(1.65 * sigma * math.sqrt(lead_time))
    reorder_point = lead_time_demand + safety_stock
    reorder_qty = max(0, math.ceil(reorder_point - product.stock))

    return {
        "sku": sku,
        "name": product.name,
        "current_stock": product.stock,
        "lead_time_weeks": lead_time,
        "lead_time_demand": lead_time_demand,
        "sigma": round(sigma, 4),
        "safety_stock": safety_stock,
        "reorder_point": reorder_point,
        "reorder_qty": reorder_qty,
    }
