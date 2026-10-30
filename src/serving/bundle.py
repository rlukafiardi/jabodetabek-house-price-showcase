"""Build the deployable bundle in serving/: the fitted model (final ensemble on the training part, the model the holdout scored),
and the reference layers the features need, in the same folder layout as data/. Run after any change to the model or the layers.
Bundle files are gitignored build artefacts; the Docker image copies serving/ into /app."""

import shutil

import joblib
import numpy as np
import pandas as pd

from src.config import EXTERNAL, ROOT, SPATIAL
from src.ingestion.inarisk import FLOOD_TIF
from src.modeling.dataset import load_usable
from src.modeling.ensemble import MODEL_FEATURES, add_words, fit_parts, target, text_model, text_scores
from src.modeling.intervals import TABLE as RANGES

SERVING = ROOT / "serving"
TEXT_SCORE_QUANTILES = (0.01, 0.99)  # the ridge text model gives extreme values for short texts full of strong words: clip to the training range


def city_by_code(train: pd.DataFrame) -> dict[str, str]:
    """Portal city name (the key of the range table) for each four-digit city code of the BIG kecamatan code."""
    code = train.kecamatan_code.astype(str).str[:4]
    return train.groupby(code).city.agg(lambda c: c.value_counts().index[0]).to_dict()


def reference_values(train: pd.DataFrame, inner_scores: np.ndarray) -> pd.Series:
    """The typical value (median) of every model input over the training listings: what "an average house" means in the explanation of an estimate."""
    return train[MODEL_FEATURES].assign(text_score=inner_scores).median()


def build() -> None:
    train = add_words(load_usable("train"))
    y = target(train)
    inner_scores, _ = text_scores(train, train.iloc[:1])
    columns = [*MODEL_FEATURES, "text_score"]
    holdout = pd.read_csv(ROOT / "reports" / "tables" / "final_test.csv", index_col="model").iloc[0]
    bundle = {
        "parts": fit_parts(train[MODEL_FEATURES].assign(text_score=inner_scores), y),
        "text_model": text_model().fit(train.words, y),
        "text_score_range": tuple(np.quantile(inner_scores, TEXT_SCORE_QUANTILES)),
        "reference": reference_values(train, inner_scores),
        "columns": columns, "age_days": float(train.age_days.min()),  # a listing posted now looks like the freshest training listing
        "ranges": pd.read_csv(RANGES, index_col="city"), "city_by_code": city_by_code(train),
        "info": {"trained_rows": len(train), "holdout_median_error": float(holdout.median_ape), "holdout_interval": [float(holdout.median_ci_low), float(holdout.median_ci_high)]},
    }
    (SERVING / "model").mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, SERVING / "model" / "model.joblib", compress=3)
    for source in [*EXTERNAL.glob("osm_*"), SPATIAL / "big_kecamatan_jabodetabek.geojson", FLOOD_TIF]:
        target_path = SERVING / source.relative_to(ROOT)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target_path)
    size = sum(f.stat().st_size for f in SERVING.rglob("*") if f.is_file()) / 1e6
    print(f"serving/ {size:.0f} MB; model.joblib {(SERVING / 'model' / 'model.joblib').stat().st_size / 1e6:.0f} MB; {len(train)} training rows")


if __name__ == "__main__":
    build()
