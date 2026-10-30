"""Learning curve: does more training data lower the error? The test folds are the usual CV folds; only the training rows of
each fold are subsampled (nested, same order for every fraction). Model: E18 (ensemble + spec fields + text score + OSM context).
Writes reports/tables/learning_curve.csv."""

import numpy as np
import pandas as pd

from src.config import ROOT
from src.features.context import CONTEXT_FEATURES
from src.modeling.compare_targets import split_folds
from src.modeling.dataset import load_usable
from src.modeling.ensemble import FEATURES, add_words, ensemble

FRACTIONS = (0.25, 0.5, 0.75, 1.0)
REPEATS = 3
RESULTS = ROOT / "reports" / "tables" / "learning_curve.csv"


def curve(df: pd.DataFrame, fit_predict, scheme: str, fraction: float) -> float:
    medians = []
    for repeat in range(REPEATS):
        pred = np.empty(len(df))
        for fold, (train_idx, test_idx) in enumerate(split_folds(df, scheme, repeat)):
            order = np.random.default_rng(1000 * repeat + fold).permutation(train_idx)
            pred[test_idx] = fit_predict(df.iloc[order[: int(len(order) * fraction)]], df.iloc[test_idx])
        error = (np.exp(pred) * df.land_area - df.price) / df.price
        medians.append(np.median(np.abs(error)))
    return float(np.mean(medians))


if __name__ == "__main__":
    df = add_words(load_usable())
    model = ensemble(FEATURES + CONTEXT_FEATURES, text=True)
    rows = []
    for scheme in ("random", "spatial"):
        for fraction in FRACTIONS:
            median_ape = curve(df, model, scheme, fraction)
            rows.append({"cv": scheme, "fraction": fraction, "train_rows": int(len(df) * 0.8 * fraction), "median_ape": round(median_ape * 100, 2)})
            print(rows[-1], flush=True)
    pd.DataFrame(rows).to_csv(RESULTS, index=False)
