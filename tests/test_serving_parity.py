"""The API must compute the same features as training. Needs the gitignored data and the built bundle (`python -m src.serving.bundle`);
skipped on a clean checkout."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.config import INTERIM
from src.modeling.ensemble import MODEL_FEATURES
from src.serving.estimator import SPEC_COLUMNS, Estimator, House

MODEL_DIR = Path(__file__).resolve().parents[1] / "serving" / "model"
pytestmark = pytest.mark.skipif(not (MODEL_DIR / "model.joblib").exists() or not (INTERIM / "portal_listings.csv").exists(),
                                reason="needs the data and the serving bundle")
NOT_COMPARED = {"age_days"} | {c for c in MODEL_FEATURES if c.startswith("txt_")}  # age is set to the freshest listing; the flags come from the notes


def test_serving_features_equal_training_features():
    from src.modeling.dataset import load_usable
    train = load_usable("train")
    sample = train[train.coord_is_centroid == 0].sample(40, random_state=0)  # the API always gets the user's own point
    estimator = Estimator(MODEL_DIR)
    columns = [c for c in MODEL_FEATURES if c not in NOT_COMPARED]
    for _, row in sample.iterrows():
        house = House(lat=row.lat, lon=row.lon, land_area=row.land_area, building_area=row.building_area, bedrooms=row.bedrooms,
                      bathrooms=row.bathrooms, floors=None if pd.isna(row.floors) else row.floors,
                      specs={c: row[c] for c in SPEC_COLUMNS if pd.notna(row[c])})
        served = estimator.features(house)[columns].iloc[0].to_numpy(float)
        np.testing.assert_allclose(served, row[columns].to_numpy(float), rtol=1e-9, atol=1e-9, equal_nan=True, err_msg=str(row.slug))


def test_factors_cover_the_inputs_and_name_only_what_the_user_filled_in():
    estimator = Estimator(MODEL_DIR)
    named = {c for cols in estimator.factor_groups().values() for c in cols}
    assert set(estimator.columns) - named == {"age_days"}, "every model input belongs to a group (age_days is fixed, not the user's)"
    plain = estimator.estimate(House(lat=-6.40, lon=106.82, land_area=120, building_area=90, bedrooms=3, bathrooms=2))["factors"]
    assert not {f["code"] for f in plain} & {"notes", "details", "floors"}, "a group the user left empty is not explained"
    assert all(abs(f["effect"]) >= 0.03 for f in plain) and [abs(f["effect"]) for f in plain] == sorted((abs(f["effect"]) for f in plain), reverse=True)
    assert len(plain) <= 4
