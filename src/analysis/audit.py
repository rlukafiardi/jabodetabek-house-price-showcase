"""Audit of the final model's headline numbers (ds-workflow phases 1, 4 and 5), no model change:
A. same-house leakage: the same house listed twice can sit on both sides of a split. Random CV with folds grouped by house against
   the usual random CV, and the holdout score with and without the listings that have a same-house listing in training.
B. benchmark: Portal's own price estimate (`minPortalvalue` / `maxPortalvalue` in each page) against the asking price, on the same listings.
C. sampling check: the 99 random pages of the `--unmatched` diagnostic (drawn from all house URLs, not by slug keyword) against the
   rest, out of fold.
Writes reports/tables/audit_*.csv. The holdout is only re-read for the overlap split of A (an audit, not a selection)."""

import gzip
import json

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

from src.analysis.error_analysis import out_of_fold
from src.config import ROOT
from src.modeling.compare_targets import FOLDS
from src.modeling.dataset import load_usable
from src.modeling.ensemble import add_words, fit_predict

TABLES = ROOT / "reports" / "tables"
RAW = ROOT / "data" / "raw"
HOUSE = ["district", "land_area", "building_area", "bedrooms", "bathrooms"]
REPEATS = 3


def apes(df: pd.DataFrame, pred: np.ndarray) -> np.ndarray:
    return np.abs(np.exp(pred) * df.land_area.to_numpy() - df.price.to_numpy()) / df.price.to_numpy()


def house_key(df: pd.DataFrame) -> pd.Series:
    return pd.Series(list(map(tuple, df[HOUSE].to_numpy())), index=df.index)


def grouped_random_cv(df: pd.DataFrame) -> float:
    """Median error of the final model with folds that keep every listing of a house on one side."""
    house = pd.factorize(house_key(df))[0]
    medians = []
    for repeat in range(REPEATS):
        pred = np.empty(len(df))
        for train_groups, test_groups in KFold(FOLDS, shuffle=True, random_state=repeat).split(np.arange(house.max() + 1)):
            train_idx, test_idx = np.flatnonzero(np.isin(house, train_groups)), np.flatnonzero(np.isin(house, test_groups))
            pred[test_idx] = fit_predict(df.iloc[train_idx], df.iloc[test_idx])
        medians.append(np.median(apes(df, pred)))
    return float(np.mean(medians))


def portal_estimate(slugs: pd.Series) -> pd.DataFrame:
    rows = []
    for slug in slugs:
        path = RAW / "portal" / f"{slug}.json.gz"
        d = json.load(gzip.open(path)) if path.exists() else {}
        rows.append({"slug": slug, "pin_min": d.get("minPortalvalue"), "pin_max": d.get("maxPortalvalue"), "pin_low_accuracy": d.get("portalvalueLowAccuracy")})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    train, test = add_words(load_usable("train")), add_words(load_usable("test"))
    out = {}

    # B and C use the usual out-of-fold errors of the final model on the training part
    oof = out_of_fold(train)
    pin = portal_estimate(oof.slug)
    oof = oof.merge(pin, on="slug", how="left").assign(pin_mid=lambda d: (d.pin_min + d.pin_max) / 2)
    have = oof[oof.pin_mid.notna() & (oof.pin_mid > 0)].copy()
    have["pin_ape"] = (have.pin_mid - have.price).abs() / have.price
    have["pin_ratio"] = have.pin_mid / have.price
    bench = pd.DataFrame([
        {"group": g, "n": len(part), "our_median_ape": part.ape.median(), "portal_median_ape": part.pin_ape.median(),
         "portal_median_ratio_to_price": part.pin_ratio.median(), "portal_ratio_p10": part.pin_ratio.quantile(.1), "portal_ratio_p90": part.pin_ratio.quantile(.9)}
        for g, part in [("all with an estimate", have), ("flagged low accuracy", have[have.pin_low_accuracy == True]),  # noqa: E712
                        ("not flagged", have[have.pin_low_accuracy != True])] if len(part)])
    bench.round(4).to_csv(TABLES / "audit_portal_benchmark.csv", index=False)
    print(f"B. Portal estimate present on {len(have)} of {len(oof)} training listings")
    print(bench.assign(**{c: bench[c] * 100 for c in ["our_median_ape", "portal_median_ape"]}).round(2).to_string(index=False))

    random_slugs = {u.rstrip("/").split("/")[-1] for u in (RAW / "portal_plan_unmatched.txt").read_text().split()}
    is_random = oof.slug.isin(random_slugs)
    sampling = pd.DataFrame([{"group": "random pages (unmatched diagnostic)", "n": int(is_random.sum()), "median_ape": oof[is_random].ape.median(),
                              "mean_ape": oof[is_random].ape.mean(), "bias": oof[is_random].signed.median()},
                             {"group": "slug-keyword sample", "n": int((~is_random).sum()), "median_ape": oof[~is_random].ape.median(),
                              "mean_ape": oof[~is_random].ape.mean(), "bias": oof[~is_random].signed.median()}])
    sampling.round(4).to_csv(TABLES / "audit_sampling.csv", index=False)
    print("\nC. random pages that are usable listings in Jabodetabek, out of fold:")
    print(sampling.assign(median_ape=sampling.median_ape * 100, mean_ape=sampling.mean_ape * 100, bias=sampling.bias * 100).round(1).to_string(index=False))

    # A: holdout with and without a same-house listing in training, then grouped random CV
    overlap = house_key(test).isin(set(house_key(train))).to_numpy()
    holdout_ape = apes(test, fit_predict(train, test))
    rng = np.random.default_rng(0)
    boot = np.sort(np.median(rng.choice(holdout_ape[~overlap], size=(2000, (~overlap).sum())), axis=1))
    leak = pd.DataFrame([{"what": "holdout, all", "n": len(test), "median_ape": np.median(holdout_ape)},
                         {"what": "holdout, with a same-house listing in training", "n": int(overlap.sum()), "median_ape": np.median(holdout_ape[overlap])},
                         {"what": "holdout, without", "n": int((~overlap).sum()), "median_ape": np.median(holdout_ape[~overlap]),
                          "ci_low": boot[50], "ci_high": boot[1949]}])
    print("\nA. holdout split by same-house overlap with training:")
    print(leak.assign(median_ape=leak.median_ape * 100).round(3).to_string(index=False))
    grouped_cv = grouped_random_cv(train)
    leak = pd.concat([leak, pd.DataFrame([{"what": "random CV, one repeat (usual folds)", "n": len(train), "median_ape": oof.ape.median()},
                                          {"what": f"random CV, folds grouped by house, {REPEATS} repeats", "n": len(train), "median_ape": grouped_cv}])])
    leak.round(4).to_csv(TABLES / "audit_same_house_leakage.csv", index=False)
    print(f"random CV usual folds {oof.ape.median():.1%} vs grouped by house {grouped_cv:.1%}")
