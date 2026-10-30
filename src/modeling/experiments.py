"""Modeling experiments (ds-workflow phase 5): one change per experiment, scored under both CV schemes, logged to a table.
Experiments whose code was removed after they were rejected (E2/E3 neighbour prices, E15 comparables, E16 size ratio and large plots,
E20 population and wealth index, E21 context + size ratio, E23 floors filled from the size ratio, E24 land title) keep their results in the log; see CLAUDE.md for the numbers."""

import sys
from collections.abc import Callable
from datetime import date

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from src.config import ROOT
from src.ingestion.parse import TEXT_FLAGS
from src.modeling.compare_targets import FEATURES, REPEATS, split_folds
from src.features.spatial import BUFFER_FEATURES
from src.features.context import CONTEXT_FEATURES
from src.modeling.dataset import load_usable
from xgboost import XGBRegressor

from src.modeling.ensemble import FEATURES as E14A_FEATURES, add_words, ensemble, text_scores
from src.modeling.final import E4_FEATURES, FACILITY_GROUP, FINAL_FEATURES, SPEC_GROUP, XGB_PARAMS
from src.modeling.final import fit_predict as final_fit_predict

RESULTS = ROOT / "reports" / "tables" / "experiments.csv"
FitPredict = Callable[[pd.DataFrame, pd.DataFrame], np.ndarray]  # (train, test) -> predicted log price per m2 of land


def target(df: pd.DataFrame) -> pd.Series:
    return np.log(df.price / df.land_area)


def gbm() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(max_iter=200, max_depth=3, learning_rate=0.05, random_state=0)


def plain(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    return gbm().fit(train[FEATURES], target(train)).predict(test[FEATURES])


def smeared(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """Duan's smearing: shift the log prediction so the back-transformed mean is unbiased."""
    model = gbm().fit(train[FEATURES], target(train))
    residual = target(train) - model.predict(train[FEATURES])
    return model.predict(test[FEATURES]) + np.log(np.mean(np.exp(residual)))


def with_text(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    features = FEATURES + list(TEXT_FLAGS)
    return gbm().fit(train[features], target(train)).predict(test[features])


def with_text_model(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    features = FEATURES + list(TEXT_FLAGS)
    train_score, test_score = text_scores(train, test)
    model = gbm().fit(train[features].assign(text_score=train_score), target(train))
    return model.predict(test[features].assign(text_score=test_score))


def xgb_on(features: list[str]) -> FitPredict:
    def fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
        return XGBRegressor(**XGB_PARAMS).fit(train[features], target(train)).predict(test[features])
    return fit_predict


def with_text_score(features: list[str]) -> FitPredict:
    def fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
        train_score, test_score = text_scores(train, test)
        model = XGBRegressor(**XGB_PARAMS).fit(train[features].assign(text_score=train_score), target(train))
        return model.predict(test[features].assign(text_score=test_score))
    return fit_predict


def run_cv(df: pd.DataFrame, fit_predict: FitPredict, scheme: str, repeats: int = REPEATS) -> tuple[dict[str, float], np.ndarray, np.ndarray]:
    """Metrics averaged over repeats, the out-of-fold predictions of repeat 0, and the median APE of each repeat."""
    per_repeat, first = [], None
    for repeat in range(repeats):
        pred = np.empty(len(df))
        for train_idx, test_idx in split_folds(df, scheme, repeat):
            pred[test_idx] = fit_predict(df.iloc[train_idx], df.iloc[test_idx])
        first = pred if first is None else first
        error = (np.exp(pred) * df.land_area - df.price) / df.price
        per_repeat.append((np.median(np.abs(error)), np.mean(np.abs(error)), np.median(error)))
    median_ape, mean_ape, bias = np.array(per_repeat).T
    metrics = {"median_ape": median_ape.mean(), "median_ape_sd": median_ape.std(), "mean_ape": mean_ape.mean(), "bias": bias.mean()}
    return metrics, first, median_ape


def log_result(name: str, scheme: str, n: int, metrics: dict[str, float]) -> None:
    row = pd.DataFrame([{"date": date.today().isoformat(), "experiment": name, "cv": scheme, "n": n,
                         **{k: round(v * 100, 2) for k, v in metrics.items()}}])
    old = pd.read_csv(RESULTS) if RESULTS.exists() else row.iloc[:0]
    old = old[~((old.experiment == name) & (old.cv == scheme))]
    pd.concat([old, row]).to_csv(RESULTS, index=False)


EXPERIMENTS: dict[str, FitPredict] = {
    "E0 gbm reference": plain,
    "E1 + smearing": smeared,
    "E4 + text flags": with_text,
    "E5 + text model score": with_text_model,
    "E8a xgb tuned, all E4 features": lambda train, test: final_fit_predict(train, test, E4_FEATURES),
    "E8 final model": lambda train, test: final_fit_predict(train, test, FINAL_FEATURES),
    "E8 final + spatial buffers": lambda train, test: final_fit_predict(train, test, FINAL_FEATURES + BUFFER_FEATURES),
    "E9a + spec fields": xgb_on(FINAL_FEATURES + SPEC_GROUP),
    "E9b + facility flags": xgb_on(FINAL_FEATURES + FACILITY_GROUP),
    "E12 ensemble xgb + extra trees + ridge": ensemble(FINAL_FEATURES),
    "E13 + text score on xgboost": with_text_score(FINAL_FEATURES),
    "E14a ensemble + spec fields + text score": ensemble(FINAL_FEATURES + SPEC_GROUP, text=True),
    "E18 ensemble + neighbourhood context": ensemble(E14A_FEATURES + CONTEXT_FEATURES, text=True),
    "E22 ensemble + text score, no spec fields": ensemble(FINAL_FEATURES, text=True),
    "E19a ensemble without extra trees (shippable)": ensemble(E14A_FEATURES, text=True, members=("xgboost", "ridge")),
    "E19b ensemble, extra trees with 20-listing leaves": ensemble(E14A_FEATURES, text=True, extra_leaf=20),
    "E14b ensemble + spec fields + facilities + text score": ensemble(FINAL_FEATURES + SPEC_GROUP + FACILITY_GROUP, text=True),
}

if __name__ == "__main__":
    df = load_usable()
    df = add_words(df)
    names = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    chosen = [n for n in EXPERIMENTS if any(arg in n for arg in names)] or list(EXPERIMENTS)
    per_repeat = {}
    for name in chosen:
        for scheme in ("random", "spatial"):
            metrics, _, per_repeat[name, scheme] = run_cv(df, EXPERIMENTS[name], scheme)
            log_result(name, scheme, len(df), metrics)
            print(f"{name:26s} {scheme:8s} median APE {metrics['median_ape']:.1%} (sd {metrics['median_ape_sd']:.1%})"
                  f" | mean APE {metrics['mean_ape']:.1%} | bias {metrics['bias']:+.1%}", flush=True)
    if "--paired" in sys.argv and len(chosen) >= 2:  # identical folds: compare each experiment with the first, repeat by repeat
        a = chosen[0]
        for b in chosen[1:]:
            for scheme in ("random", "spatial"):
                diff = (per_repeat[b, scheme] - per_repeat[a, scheme]) * 100
                print(f"{b} minus {a}, {scheme}: mean {diff.mean():+.2f} points, better in {int((diff < 0).sum())}/{len(diff)} repeats")
