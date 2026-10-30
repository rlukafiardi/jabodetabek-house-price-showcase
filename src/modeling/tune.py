"""E6: random search per model family on the training part. Each configuration is scored by spatial-block CV
(3 repeats); the best per family is then re-scored with full 5x5 CV under both schemes, paired against E4."""

import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.ensemble import ExtraTreesRegressor, GradientBoostingRegressor, HistGradientBoostingRegressor
from sklearn.linear_model import HuberRegressor
from sklearn.model_selection import ParameterGrid, ParameterSampler
from xgboost import XGBRegressor

from src.config import ROOT
from src.modeling.experiments import gbm, log_result, run_cv
from src.modeling.model_zoo import prepared, using
from src.modeling.dataset import load_usable

SEARCH_REPEATS, CONFIGS_PER_MODEL = 3, 16
RESULTS = ROOT / "reports" / "tables" / "tuning.csv"
E4_PARAMS = {"max_iter": 200, "max_depth": 3, "learning_rate": 0.05}

# name -> (builder taking params, search space, sampled or full grid); boosters with native missing-value handling are used raw
SPACES = {
    "hist gbm": (lambda p: HistGradientBoostingRegressor(random_state=0, **p),
                 {"learning_rate": [0.02, 0.05, 0.1], "max_depth": [2, 3, 4, None], "max_iter": [150, 300, 600],
                  "min_samples_leaf": [10, 20, 40], "l2_regularization": [0.0, 1.0, 5.0], "max_features": [0.5, 1.0]}, "sample"),
    "gradient boosting": (lambda p: prepared(GradientBoostingRegressor(random_state=0, **p)),
                          {"n_estimators": [150, 300, 600], "learning_rate": [0.02, 0.05, 0.1], "max_depth": [2, 3, 4],
                           "subsample": [0.7, 1.0], "min_samples_leaf": [1, 5, 15], "max_features": [0.5, 1.0]}, "sample"),
    "extra trees": (lambda p: prepared(ExtraTreesRegressor(n_estimators=300, n_jobs=-1, random_state=0, **p)),
                    {"max_features": [0.2, 0.33, 0.5, 0.8, 1.0], "min_samples_leaf": [1, 2, 4, 8], "max_depth": [None, 12]}, "sample"),
    "huber": (lambda p: prepared(HuberRegressor(max_iter=2000, **p)),
              {"epsilon": [1.1, 1.35, 1.6, 2.0], "alpha": [1e-4, 1e-2, 1.0]}, "grid"),
    "lightgbm": (lambda p: LGBMRegressor(random_state=0, verbose=-1, subsample_freq=1, **p),
                 {"n_estimators": [200, 400, 800], "learning_rate": [0.02, 0.05, 0.1], "num_leaves": [7, 15, 31],
                  "min_child_samples": [10, 20, 40], "subsample": [0.7, 1.0], "colsample_bytree": [0.5, 0.8, 1.0], "reg_lambda": [0.0, 1.0, 5.0]}, "sample"),
    "xgboost": (lambda p: XGBRegressor(random_state=0, **p),
                {"n_estimators": [200, 400, 800], "learning_rate": [0.02, 0.05, 0.1], "max_depth": [2, 3, 4, 6], "min_child_weight": [1, 3, 10],
                 "subsample": [0.7, 1.0], "colsample_bytree": [0.5, 0.8, 1.0], "reg_lambda": [1.0, 5.0]}, "sample"),
}


def configs(space: dict, mode: str) -> list[dict]:
    return list(ParameterGrid(space)) if mode == "grid" else list(ParameterSampler(space, CONFIGS_PER_MODEL, random_state=0))


if __name__ == "__main__":
    df = load_usable()
    rows, best = [], {}
    for family, (build, space, mode) in SPACES.items():
        candidates = configs(space, mode) + ([E4_PARAMS] if family == "hist gbm" else [])
        for params in candidates:
            metrics, _, _ = run_cv(df, using(lambda b=build, p=params: b(p)), "spatial", repeats=SEARCH_REPEATS)
            rows.append({"family": family, "params": params, "spatial_median_ape_3rep": metrics["median_ape"]})
        family_rows = [r for r in rows if r["family"] == family]
        best[family] = min(family_rows, key=lambda r: r["spatial_median_ape_3rep"])["params"]
        print(f"{family:18s} searched {len(candidates)} configs, best {min(r['spatial_median_ape_3rep'] for r in family_rows):.1%}: {best[family]}", flush=True)
    pd.DataFrame(rows).sort_values(["family", "spatial_median_ape_3rep"]).to_csv(RESULTS, index=False)

    final, per_repeat = [], {}
    for scheme in ("random", "spatial"):
        _, _, per_repeat["E4", scheme] = run_cv(df, using(gbm), scheme)
    for family, params in best.items():
        build = SPACES[family][0]
        for scheme in ("random", "spatial"):
            metrics, _, per_repeat[family, scheme] = run_cv(df, using(lambda b=build, p=params: b(p)), scheme)
            log_result(f"E6 tuned {family}", scheme, len(df), metrics)
            wins = int(((per_repeat[family, scheme] - per_repeat["E4", scheme]) < 0).sum())
            final.append({"family": family, "cv": scheme, "median_ape": metrics["median_ape"] * 100, "mean_ape": metrics["mean_ape"] * 100, "wins_vs_E4": wins})
    table = pd.DataFrame(final).pivot(index="family", columns="cv", values=["median_ape", "mean_ape", "wins_vs_E4"])
    print(table.round(1).sort_values(("median_ape", "spatial")).to_string())
