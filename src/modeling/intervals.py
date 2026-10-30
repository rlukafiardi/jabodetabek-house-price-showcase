"""Prediction ranges for the app (split-conformal style). Out-of-fold errors of the final model under spatial-block CV (the
honest case for a place the model has not seen) give, per city, the 10th and 90th percentile of actual / predicted price; the
app shows estimate x low to estimate x high as an 80% range, with a narrower 50% range (25th to 75th percentile) as the likely part. Cities with fewer than MIN_PER_CITY errors fall back to all cities.
Training part only; coverage on the holdout is checked once in the final evaluation."""

import numpy as np
import pandas as pd

from src.config import ROOT
from src.modeling.compare_targets import split_folds
from src.modeling.dataset import load_usable
from src.modeling.ensemble import add_words, fit_predict

TABLE = ROOT / "reports" / "tables" / "prediction_ranges.csv"
LOW, HIGH = 0.10, 0.90
LOW_50, HIGH_50 = 0.25, 0.75
MIN_PER_CITY = 100
LARGE_PLOT_M2 = 300  # plots above this are priced by the building and the land value: error 31.6% against about 20% (error analysis)
LARGE_PLOTS = "large plots"
REPEATS = 2


def out_of_fold_log_ratio(df: pd.DataFrame, repeats: int = REPEATS) -> pd.DataFrame:
    """log(actual price / predicted price) for every training listing, stacked over spatial-block CV repeats."""
    rows = []
    for repeat in range(repeats):
        pred = np.empty(len(df))
        for train_idx, test_idx in split_folds(df, "spatial", repeat):
            pred[test_idx] = fit_predict(df.iloc[train_idx], df.iloc[test_idx])
        rows.append(pd.DataFrame({"city": df.city.to_numpy(), "land_area": df.land_area.to_numpy(), "log_ratio": np.log(df.price / df.land_area).to_numpy() - pred}))
    return pd.concat(rows, ignore_index=True)


def range_table(errors: pd.DataFrame) -> pd.DataFrame:
    """Multipliers of the point estimate (80% range: low, high; 50% range: low_50, high_50) for each city and for 'all cities'."""
    def quantiles(part: pd.Series) -> dict[str, float]:
        return {"low": float(np.exp(part.quantile(LOW))), "high": float(np.exp(part.quantile(HIGH))),
                "low_50": float(np.exp(part.quantile(LOW_50))), "high_50": float(np.exp(part.quantile(HIGH_50))), "n": len(part) // REPEATS}
    table = {"all cities": quantiles(errors.log_ratio)}
    table |= {city: quantiles(part.log_ratio) for city, part in errors.groupby("city") if len(part) >= MIN_PER_CITY * REPEATS}
    large = errors[errors.land_area > LARGE_PLOT_M2]
    if len(large) >= MIN_PER_CITY * REPEATS:
        table[LARGE_PLOTS] = quantiles(large.log_ratio)  # all cities together: too few large plots per city
    return pd.DataFrame(table).T.rename_axis("city")


def apply_range(estimate: np.ndarray, city: pd.Series, table: pd.DataFrame, column: str = "",
                land_area: pd.Series | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Range around the estimates: the 80% range by default, column="_50" for the 50% range. With land_area, plots above
    LARGE_PLOT_M2 get the large-plot range instead of their city's."""
    row = table.reindex(city).fillna(table.loc["all cities"])
    if land_area is not None and LARGE_PLOTS in table.index:
        row.loc[land_area.to_numpy() > LARGE_PLOT_M2, :] = table.loc[LARGE_PLOTS, row.columns].to_numpy()
    return estimate * row[f"low{column}"].to_numpy(), estimate * row[f"high{column}"].to_numpy()


if __name__ == "__main__":
    train = add_words(load_usable("train"))
    table = range_table(out_of_fold_log_ratio(train))
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    table.round(3).to_csv(TABLE)
    print(table.round(2).to_string())

    # coverage check without the test set: calibrate on one half of the listings, count on the other half (same listing in
    # both repeats stays in the same half)
    errors = out_of_fold_log_ratio(train)
    half = np.tile(np.arange(len(train)) % 2, REPEATS).astype(bool)
    calibrated = range_table(errors[~half].reset_index(drop=True))
    check = errors[half]
    for label, size_aware in (("city only", False), ("city + large plots", True)):
        low, high = apply_range(np.ones(len(check)), check.city, calibrated, land_area=check.land_area if size_aware else None)
        inside = (np.exp(check.log_ratio.to_numpy()) >= low) & (np.exp(check.log_ratio.to_numpy()) <= high)
        large = (check.land_area > LARGE_PLOT_M2).to_numpy()
        print(f"{label}: 80% range covers {inside.mean():.1%} overall, {inside[large].mean():.1%} on plots over {LARGE_PLOT_M2} m², {inside[~large].mean():.1%} on the rest")
