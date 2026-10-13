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

    for sku in history:
        history[sku].sort(key=lambda item: item[0])
        dates = [week for week, _ in history[sku]]
        if len(dates) != len(set(dates)):
            raise ValueError(f"Duplicate weekly records for {sku}")
    return history


def report(name, pairs):
    if not pairs:
        print(f"{name}: insufficient history")
        return

    absolute_errors = [
        abs(actual - predicted) for actual, predicted in pairs
    ]
    total_actual = sum(actual for actual, _ in pairs)
    mae = sum(absolute_errors) / len(pairs)
    wape = (
        100 * sum(absolute_errors) / total_actual
        if total_actual else float("nan")
    )
    print(
        f"{name}: MAE={mae:.3f}, WAPE={wape:.2f}%, "
        f"n={len(pairs)}"
    )


def main():
    root = Path(__file__).resolve().parent.parent
    history = load_history(root / "data" / "sales_history.csv")
    common = {
        "Naive": [],
        "12-week average": [],
        "Seasonal naive (52 weeks)": [],
    }
    wider_average = []

    for sku, rows in sorted(history.items()):
        values = [units for _, units in rows]

        # Common comparison: all methods have 52 earlier observations.
        for index in range(52, len(values)):
            actual = values[index]
            common["Naive"].append((actual, values[index - 1]))
            common["12-week average"].append(
                (actual, sum(values[index - 12:index]) / 12)
            )
            common["Seasonal naive (52 weeks)"].append(
                (actual, values[index - 52])
            )

        # Additional evaluation for the 12-week average only.
        for index in range(12, len(values)):
            wider_average.append(
                (values[index], sum(values[index - 12:index]) / 12)
            )

    print("Rolling one-week-ahead backtest")
    print("Common evaluation set: 52 prior observations required")
    for name, pairs in common.items():
        report(name, pairs)

    print()
    print("12-week average on its wider eligible evaluation set")
    report("12-week average", wider_average)


if __name__ == "__main__":
    main()
