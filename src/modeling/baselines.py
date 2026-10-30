import numpy as np
import pandas as pd

from src.modeling.compare_targets import REPEATS, evaluate, split_folds
from src.modeling.dataset import load_usable


def group_median_baseline(df: pd.DataFrame, scheme: str, groups: list[str]) -> dict[str, float]:
    """Predict price per m2 of land as the median of the first group level with training data: kecamatan, then city, then all."""
    y = np.log(df.price / df.land_area)
    per_repeat = []
    for repeat in range(REPEATS):
        pred = np.empty(len(df))
        for train_idx, test_idx in split_folds(df, scheme, repeat):
            train, test = df.iloc[train_idx], df.iloc[test_idx]
            guess = pd.Series(y.iloc[train_idx].median(), index=test.index)
            for group in reversed(groups):  # most specific level last, so it wins
                level = y.iloc[train_idx].groupby(train[group]).median()
                known = test[group].map(level)
                guess = known.fillna(guess)
            pred[test_idx] = guess.to_numpy()
        error = (np.exp(pred) * df.land_area - df.price) / df.price
        per_repeat.append((np.median(np.abs(error)), np.mean(np.abs(error)), np.median(error)))
    median_ape, mean_ape, bias = np.array(per_repeat).T
    return {"median_ape": median_ape.mean(), "median_ape_sd": median_ape.std(), "mean_ape": mean_ape.mean(), "bias": bias.mean()}


if __name__ == "__main__":
    df = load_usable()
    rows = []
    for scheme in ("random", "spatial"):
        rows.append({"cv": scheme, "model": "B0 city median", **group_median_baseline(df, scheme, ["city"])})
        rows.append({"cv": scheme, "model": "B1 kecamatan median (fallback city)", **group_median_baseline(df, scheme, ["kecamatan_code", "city"])})
        for model in ("ridge", "gbm"):
            rows.append({"cv": scheme, "model": model, **evaluate(df, scheme, model, "land_area")})
    table = pd.DataFrame(rows)
    print(f"{len(df)} training listings")
    print(table.assign(median_ape=lambda t: (t.median_ape * 100).round(1), median_ape_sd=lambda t: (t.median_ape_sd * 100).round(1),
                       mean_ape=lambda t: (t.mean_ape * 100).round(1), bias=lambda t: (t.bias * 100).round(1)).to_string(index=False))
