"""Error analysis (ds-workflow phase 6): where the final model's error sits, from out-of-fold predictions on the training part
(one random-CV repeat, the deliverable's case; the test set is not used). Writes reports/tables/error_analysis.csv and prints the
tail shares. Run after a model change to see whether a segment moved."""

import numpy as np
import pandas as pd

from src.config import ROOT
from src.modeling.compare_targets import split_folds
from src.modeling.dataset import load_usable
from src.modeling.ensemble import add_words, fit_predict
from src.modeling.intervals import LARGE_PLOT_M2

TABLE = ROOT / "reports" / "tables" / "error_analysis.csv"
TAIL = ROOT / "reports" / "tables" / "error_analysis_tail.csv"


def out_of_fold(df: pd.DataFrame, predict=fit_predict) -> pd.DataFrame:
    pred = np.empty(len(df))
    for train_idx, test_idx in split_folds(df, "random", 0):
        pred[test_idx] = predict(df.iloc[train_idx], df.iloc[test_idx])
    estimate = np.exp(pred) * df.land_area
    return df.assign(ape=(estimate - df.price).abs() / df.price, signed=(estimate - df.price) / df.price, ppm2=df.price / df.land_area)


def segments(df: pd.DataFrame) -> dict[str, pd.Series]:
    floors = df.floors.fillna(-1).map(lambda v: "missing" if v < 0 else ("1" if v <= 1 else ("2" if v <= 2 else "3+")))
    return {
        "price per m² quartile": pd.qcut(df.ppm2, 4, labels=["cheapest 25%", "2nd", "3rd", "dearest 25%"]),
        "land area": pd.cut(df.land_area, [0, 60, 90, 120, 200, LARGE_PLOT_M2, 1e6], labels=["<60", "60-90", "90-120", "120-200", f"200-{LARGE_PLOT_M2}", f">{LARGE_PLOT_M2}"]),
        "floors stated": floors,
        "coordinate": df.coord_is_centroid.map({0: "own", 1: "district centroid"}),
        "description length": pd.qcut(df.words.str.len(), 4, labels=["shortest 25%", "2nd", "3rd", "longest 25%"]),
        "city": df.city,
    }


if __name__ == "__main__":
    df = out_of_fold(add_words(load_usable("train")))
    ape = df.ape.sort_values(ascending=False)
    print(f"n={len(df)} median {df.ape.median():.1%} mean {df.ape.mean():.1%}; within 10% {(df.ape <= .1).mean():.0%}, within 20% {(df.ape <= .2).mean():.0%}, "
          f"over 50% {(df.ape > .5).mean():.0%}; worst 10% carry {ape.iloc[:len(df) // 10].sum() / ape.sum():.0%} of the absolute error")
    pd.DataFrame([{"n": len(df), "median_ape": df.ape.median(), "mean_ape": df.ape.mean(), "within_10pct": (df.ape <= .1).mean(),
                   "within_20pct": (df.ape <= .2).mean(), "over_50pct": (df.ape > .5).mean(),
                   "worst_10pct_share_of_error": ape.iloc[:len(df) // 10].sum() / ape.sum(),
                   "worst_25pct_share_of_error": ape.iloc[:len(df) // 4].sum() / ape.sum()}]).round(4).to_csv(TAIL, index=False)
    rows = []
    for name, key in segments(df).items():
        g = df.groupby(key, observed=True).agg(n=("ape", "size"), median_ape=("ape", "median"), bias=("signed", "median"))
        rows.append(g.rename_axis("segment").reset_index().assign(group=name))
    table = pd.concat(rows)[["group", "segment", "n", "median_ape", "bias"]]
    table.round(4).to_csv(TABLE, index=False)
    print(table.assign(median_ape=table.median_ape * 100, bias=table.bias * 100).round(1).to_string(index=False))
