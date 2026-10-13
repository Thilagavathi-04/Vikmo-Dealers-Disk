
import csv
from collections import defaultdict
from pathlib import Path


def load_history(path):
    history = defaultdict(list)
    with path.open(newline="", encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            history[row["sku"]].append(
                (row["week_start"], int(row["units_sold"]))
            )

    for sku, rows in history.items():
        rows.sort(key=lambda row: row[0])
        dates = [row[0] for row in rows]
        if len(dates) != len(set(dates)):
            raise ValueError(f"Duplicate dates for {sku}")
        for previous, current in zip(dates, dates[1:]):
            from datetime import date
            if (date.fromisoformat(current) -
                    date.fromisoformat(previous)).days != 7:
                raise ValueError(f"Non-weekly gap for {sku}")
    return history


def metrics(pairs):
    if not pairs:
        return "no eligible observations"
    errors = [abs(actual - pred) for actual, pred in pairs]
    total = sum(actual for actual, _ in pairs)
    mae = sum(errors) / len(errors)
    wape = 100 * sum(errors) / total if total else float("nan")
    return f"MAE={mae:.3f}, WAPE={wape:.2f}%, n={len(pairs)}"


def main():
    root = Path(__file__).resolve().parent.parent
    history = load_history(root / "data" / "sales_history.csv")

    methods = ["Last value", "12-observation average",
               "Same week last year"]
    overall = {name: [] for name in methods}
    by_horizon = {
        h: {name: [] for name in methods}
        for h in range(1, 5)
    }
    origins = 0

    for sku, rows in sorted(history.items()):
        values = [units for _, units in rows]

        # Require 52 past observations and four actual future weeks
        # so all three methods use the exact same evaluation cases.
        for origin in range(52, len(values) - 3):
            past = values[:origin]  # no future data enters prediction
            predictions = {
                "Last value": [past[-1]] * 4,
                "12-observation average": [
                    round(sum(past[-12:]) / 12)
                ] * 4,
                "Same week last year": [
                    values[origin + h - 52] for h in range(4)
                ],
            }

            origins += 1
            for h in range(4):
                actual = values[origin + h]
                for name in methods:
                    pair = (actual, predictions[name][h])
                    by_horizon[h + 1][name].append(pair)
                    overall[name].append(pair)

    print("FOUR-WEEK ROLLING HISTORICAL BACKTEST")
    print("Common evaluation set: 52 prior observations required")
    print("Forecasts use only observations before each origin.")
    print("Forecast origins evaluated:", origins)
    print("\nOverall metrics across horizons 1-4:")
    for name in methods:
        print(f"{name}: {metrics(overall[name])}")

    print("\nMetrics by forecast horizon:")
    for h in range(1, 5):
        print(f"\nWeek {h}:")
        for name in methods:
            print(f"  {name}: {metrics(by_horizon[h][name])}")


if __name__ == "__main__":
    main()
