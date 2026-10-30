"""How fast does the model go stale? For each later month, a model trained on listings created before that month (the past) is
compared with a model trained on the same number of listings drawn from all other months (mixed): the gap is the cost of time at
equal data size. Also writes the drift table (first months against the last months) and the monthly price level per m².
Writes reports/tables/temporal_backtest.csv, drift_early_vs_late.csv. Training part only."""

import numpy as np
import pandas as pd

from src.config import ROOT
from src.modeling.dataset import load_usable
from src.modeling.ensemble import MODEL_FEATURES, add_words, fit_predict
from src.pipeline.monitor import drift_table, performance

TABLES = ROOT / "reports" / "tables"
TARGET_MONTHS = ["2026-05", "2026-06", "2026-07", "2026-08"]


def score(train: pd.DataFrame, test: pd.DataFrame) -> dict[str, float]:
    estimate = np.exp(fit_predict(train, test)) * test.land_area
    return performance((estimate - test.price).abs() / test.price, (estimate - test.price) / test.price)


if __name__ == "__main__":
    df = add_words(load_usable("train"))
    month = df.created_at.dt.tz_localize(None).dt.to_period("M").astype(str)
    rows = []
    for m in TARGET_MONTHS:
        test, past = df[month == m], df[month < m]
        mixed = df[month != m].sample(len(past), random_state=0)
        for name, train in (("past", past), ("mixed", mixed)):
            rows.append({"target_month": m, "train": name, "train_rows": len(train), **score(train, test)})
            print(rows[-1], flush=True)
    result = pd.DataFrame(rows)
    result.round(4).to_csv(TABLES / "temporal_backtest.csv", index=False)

    early, late = df[month <= "2026-03"], df[month >= "2026-06"]
    drift_table(early, late, [f for f in MODEL_FEATURES if f != "age_days"]).round(3).to_csv(TABLES / "drift_early_vs_late.csv", index=False)
    print(drift_table(early, late, [f for f in MODEL_FEATURES if f != "age_days"]).head(8).round(3).to_string(index=False))
    level = df.assign(month=month, ppm2=df.price / df.land_area).groupby("month").ppm2.median() / 1e6
    print("median price per m² by month (M IDR):", level.round(1).to_dict())
