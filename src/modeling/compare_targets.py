import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import RidgeCV
from sklearn.model_selection import KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.modeling.dataset import FLOOD, FLOORS, SPATIAL_PLUS, load_usable

FEATURES = SPATIAL_PLUS + FLOOD + FLOORS  # SPATIAL_PLUS already contains the basic and centroid-flag features
TARGETS = {  # name -> column the price is divided by (None: log price, sizes are plain features)
    "log price per m2 of land": "land_area",
    "log price per m2 of building": "building_area",
    "log price": None,
}
MODELS = {
    "gbm": lambda: HistGradientBoostingRegressor(max_iter=200, max_depth=3, learning_rate=0.05, random_state=0),
    "ridge": lambda: make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), RidgeCV(alphas=np.logspace(-2, 3, 20))),
}
REPEATS, FOLDS, BLOCK_DEGREES = 5, 5, 0.1  # a 0.1 degree block is about 11 km, above the ~10 km range of spatial dependence


def split_folds(df: pd.DataFrame, scheme: str, repeat: int):
    if scheme == "random":
        yield from KFold(FOLDS, shuffle=True, random_state=repeat).split(df)
        return
    blocks = pd.factorize((np.floor(df.lat / BLOCK_DEGREES) * 10_000 + np.floor(df.lon / BLOCK_DEGREES)).to_numpy())[0]
    fold_of_block = np.random.default_rng(repeat).permutation(blocks.max() + 1) % FOLDS
    fold = fold_of_block[blocks]
    for k in range(FOLDS):
        yield np.flatnonzero(fold != k), np.flatnonzero(fold == k)


def evaluate(df: pd.DataFrame, scheme: str, model: str, divisor: str | None) -> dict[str, float]:
    scale = df[divisor] if divisor else pd.Series(1.0, index=df.index)
    y = np.log(df.price / scale)
    per_repeat = []
    for repeat in range(REPEATS):
        pred = np.empty(len(df))
        for train_idx, test_idx in split_folds(df, scheme, repeat):
            fitted = MODELS[model]().fit(df.iloc[train_idx][FEATURES], y.iloc[train_idx])
            pred[test_idx] = fitted.predict(df.iloc[test_idx][FEATURES])
        error = (np.exp(pred) * scale - df.price) / df.price
        per_repeat.append((np.median(np.abs(error)), np.mean(np.abs(error)), np.median(error)))
    median_ape, mean_ape, bias = np.array(per_repeat).T
    return {"median_ape": median_ape.mean(), "median_ape_sd": median_ape.std(), "mean_ape": mean_ape.mean(), "bias": bias.mean()}


if __name__ == "__main__":
    df = load_usable()
    print(f"{len(df)} training listings, {len(FEATURES)} features, {REPEATS} repeats of {FOLDS}-fold CV")
    rows = []
    for scheme in ("random", "spatial blocks"):
        for model in MODELS:
            for name, divisor in TARGETS.items():
                rows.append({"cv": scheme, "model": model, "target": name, **evaluate(df, scheme.split()[0], model, divisor)})
    table = pd.DataFrame(rows)
    print(table.assign(median_ape=lambda t: (t.median_ape * 100).round(1), median_ape_sd=lambda t: (t.median_ape_sd * 100).round(1),
                       mean_ape=lambda t: (t.mean_ape * 100).round(1), bias=lambda t: (t.bias * 100).round(1)).to_string(index=False))
