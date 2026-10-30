"""Final evaluation (ds-workflow phase 6): fit on the whole training part, score the held-out test set once.
Writes reports/tables/final_test*.csv. Do not rerun to compare variants: the test set is for the final number only."""

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from src.config import ROOT
from src.modeling.dataset import load_usable
from src.modeling.ensemble import MODEL_FEATURES, add_words, fit_predict as final_predict
from src.modeling.experiments import gbm
from src.modeling.final import E4_FEATURES, FINAL_FEATURES
from src.modeling.final import fit_predict as xgboost_predict
from src.modeling.intervals import TABLE as RANGES, apply_range
from src.modeling.model_zoo import prepared

TABLES = ROOT / "reports" / "tables"
BOOTSTRAP = 2000


def target(df: pd.DataFrame) -> pd.Series:
    return np.log(df.price / df.land_area)


def group_median(train: pd.DataFrame, test: pd.DataFrame, groups: list[str]) -> np.ndarray:
    guess = pd.Series(target(train).median(), index=test.index)
    for group in reversed(groups):
        guess = test[group].map(target(train).groupby(train[group]).median()).fillna(guess)
    return guess.to_numpy()


def summary(ape: np.ndarray, signed: np.ndarray) -> dict[str, float]:
    rng = np.random.default_rng(0)
    boot = rng.choice(ape, size=(BOOTSTRAP, len(ape)), replace=True)
    medians, means = np.median(boot, axis=1), boot.mean(axis=1)
    return {"median_ape": np.median(ape), "median_ci_low": np.quantile(medians, 0.025), "median_ci_high": np.quantile(medians, 0.975),
            "mean_ape": ape.mean(), "mean_ci_low": np.quantile(means, 0.025), "mean_ci_high": np.quantile(means, 0.975),
            "bias": np.median(signed), "within_20pct": (ape <= 0.2).mean()}


if __name__ == "__main__":
    train, test = add_words(load_usable("train")), add_words(load_usable("test"))
    predictions = {
        "ensemble + spec + context + text score (final)": final_predict(train, test),
        "xgboost tuned (previous final)": xgboost_predict(train, test, FINAL_FEATURES),
        "linear regression (explanatory)": prepared(LinearRegression()).fit(train[E4_FEATURES], target(train)).predict(test[E4_FEATURES]),
        "E4 hist gbm": gbm().fit(train[E4_FEATURES], target(train)).predict(test[E4_FEATURES]),
        "B1 kecamatan median": group_median(train, test, ["kecamatan_code", "city"]),
        "B0 city median": group_median(train, test, ["city"]),
    }
    rows, errors = [], {}
    for name, pred in predictions.items():
        signed = (np.exp(pred) * test.land_area - test.price) / test.price
        errors[name] = np.abs(signed)
        rows.append({"model": name, **summary(np.abs(signed.to_numpy()), signed.to_numpy())})
    table = pd.DataFrame(rows).set_index("model")
    table.round(4).to_csv(TABLES / "final_test.csv")
    final = test.assign(ape=errors["ensemble + spec + context + text score (final)"].to_numpy())
    by_city = final.groupby("city").ape.agg(n="size", median_ape="median").sort_values("median_ape")
    by_precision = final.groupby(final.coord_is_centroid.map({0: "own coordinates", 1: "district centroid"})).ape.agg(n="size", median_ape="median")
    pd.concat([by_city.assign(segment="city"), by_precision.assign(segment="location precision")]).round(4).to_csv(TABLES / "final_test_segments.csv")
    ranges = pd.read_csv(RANGES, index_col="city")  # built on the training part only (src/modeling/intervals.py)
    point = np.exp(predictions["ensemble + spec + context + text score (final)"]) * test.land_area
    coverage = {}
    for label, column in (("80%", ""), ("50%", "_50")):
        low, high = apply_range(point.to_numpy(), test.city, ranges, column, test.land_area)
        coverage[label] = float(((test.price.to_numpy() >= low) & (test.price.to_numpy() <= high)).mean())
    pd.Series(coverage, name="holdout_coverage").round(4).to_csv(TABLES / "final_test_range_coverage.csv")
    print(f"range coverage on the holdout: {coverage}")
    print(f"test listings: {len(test)} | training listings: {len(train)} | features: {len(MODEL_FEATURES)} + text score")
    print((table * 100).round(1).to_string())
    print((by_city.assign(median_ape=by_city.median_ape * 100)).round(1).to_string())
    print((by_precision.assign(median_ape=by_precision.median_ape * 100)).round(1).to_string())
