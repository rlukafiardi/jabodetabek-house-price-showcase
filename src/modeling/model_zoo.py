"""Screen regression model families on the E4 features with scikit-learn default settings (no tuning), paired against
the current E4 model on identical folds. Every model gets the same preprocessing: median imputation with missing flags,
feature scaling, and a standardised target. The test set is not used."""

import sys

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import (AdaBoostRegressor, BaggingRegressor, ExtraTreesRegressor, GradientBoostingRegressor,
                              HistGradientBoostingRegressor, RandomForestRegressor)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, HuberRegressor, Lasso, LinearRegression, Ridge
from sklearn.neighbors import KNeighborsRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR
from sklearn.tree import DecisionTreeRegressor
from xgboost import XGBRegressor

from src.ingestion.parse import TEXT_FLAGS
from src.modeling.compare_targets import FEATURES
from src.modeling.experiments import gbm, log_result, run_cv, target
from src.modeling.dataset import load_usable

E4_FEATURES = FEATURES + list(TEXT_FLAGS)
REFERENCE = "E4 hist gbm (our settings)"

DEFAULT_MODELS = {  # random_state is fixed for reproducibility only
    "linear regression": LinearRegression,
    "ridge": Ridge,
    "lasso": Lasso,
    "elastic net": ElasticNet,
    "huber": HuberRegressor,
    "knn": KNeighborsRegressor,
    "svr": SVR,
    "decision tree": lambda: DecisionTreeRegressor(random_state=0),
    "random forest": lambda: RandomForestRegressor(random_state=0),
    "extra trees": lambda: ExtraTreesRegressor(random_state=0),
    "bagging": lambda: BaggingRegressor(random_state=0),
    "adaboost": lambda: AdaBoostRegressor(random_state=0),
    "gradient boosting": lambda: GradientBoostingRegressor(random_state=0),
    "hist gradient boosting": lambda: HistGradientBoostingRegressor(random_state=0),
    "mlp": lambda: MLPRegressor(random_state=0),
    "xgboost": lambda: XGBRegressor(random_state=0),
    "lightgbm": lambda: LGBMRegressor(random_state=0, verbose=-1),
}


def prepared(model):
    pipeline = make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(), model)
    return TransformedTargetRegressor(regressor=pipeline, transformer=StandardScaler())


def using(factory):
    def fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
        return factory().fit(train[E4_FEATURES], target(train)).predict(test[E4_FEATURES])
    return fit_predict


if __name__ == "__main__":
    df = load_usable()
    wanted = sys.argv[1:] or list(DEFAULT_MODELS)  # e.g. `xgboost lightgbm` to run only those (always with the reference)
    candidates = {name: (lambda f=factory: prepared(f())) for name, factory in DEFAULT_MODELS.items() if name in wanted} | {REFERENCE: gbm}
    rows, per_repeat = [], {}
    for name, factory in candidates.items():
        for scheme in ("random", "spatial"):
            metrics, _, per_repeat[name, scheme] = run_cv(df, using(factory), scheme)
            log_result(f"D {name}", scheme, len(df), metrics)
            rows.append({"model": name, "cv": scheme, **metrics})
        print(f"{name:28s} done", flush=True)
    table = pd.DataFrame(rows).pivot(index="model", columns="cv", values=["median_ape", "mean_ape"]) * 100
    for scheme in ("random", "spatial"):
        table[("wins vs E4", scheme)] = [int(((per_repeat[m, scheme] - per_repeat[REFERENCE, scheme]) < 0).sum()) for m in table.index]
    print(table.round(1).sort_values(("median_ape", "spatial")).to_string())
