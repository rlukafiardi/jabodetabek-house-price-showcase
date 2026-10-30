"""The chosen model: tuned XGBoost (E6) on the E4 features, minus groups dropped by the E7 ablation."""

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from src.ingestion.parse import SPEC_FEATURES, TEXT_FLAGS
from src.modeling.compare_targets import FEATURES

E4_FEATURES = FEATURES + list(TEXT_FLAGS)
XGB_PARAMS = {"n_estimators": 400, "max_depth": 3, "learning_rate": 0.02, "subsample": 0.7, "colsample_bytree": 0.8,
              "min_child_weight": 1, "reg_lambda": 5.0, "random_state": 0}  # best of the E6 search (spatial-block CV)
DROPPED_GROUPS = ["amenity distances", "toll distance"]  # E7: dropping them did not hurt spatial-block CV
FEATURE_GROUPS = {
    "coordinates": ["lat", "lon"],
    "km to Monas": ["dist_monas_km"],
    "transit distances": ["dist_station_km", "dist_krl_km", "dist_mrt_lrt_km", "dist_busway_km"],
    "toll distance": ["dist_toll_km"],
    "amenity distances": ["dist_mall_km", "dist_hospital_km", "dist_university_km"],
    "flood index": ["flood_index"],
    "floors": ["floors", "floors_missing"],
    "centroid flag": ["coord_is_centroid"],
    "listing age": ["age_days"],
    "text flags": list(TEXT_FLAGS),
    "rooms": ["bedrooms", "bathrooms"],
}
SPEC_GROUP = [f for f in SPEC_FEATURES if not f.startswith("fac_")]  # candidates for E9, not in the final model yet
FACILITY_GROUP = [f for f in SPEC_FEATURES if f.startswith("fac_")]
FINAL_FEATURES = [f for f in E4_FEATURES if not any(f in FEATURE_GROUPS[g] for g in DROPPED_GROUPS)]


def final_model() -> XGBRegressor:
    return XGBRegressor(**XGB_PARAMS)


def fit_predict(train: pd.DataFrame, test: pd.DataFrame, features: list[str] = FINAL_FEATURES) -> np.ndarray:
    """Predicted log price per m² of land."""
    return final_model().fit(train[features], np.log(train.price / train.land_area)).predict(test[features])
