import numpy as np
import pandas as pd

from src.features.admin import add_admin_areas
from src.features.context import add_context_features
from src.features.spatial import add_spatial_features
from src.modeling.split import TEST_SLUGS, usable_listings

BASIC = ["log_land", "log_building", "bedrooms", "bathrooms", "lat", "lon", "age_days"]
FLAG = ["coord_is_centroid"]
SPATIAL = BASIC + FLAG + ["dist_station_km", "dist_toll_km", "dist_monas_km"]
SPATIAL_PLUS = SPATIAL + ["dist_krl_km", "dist_mrt_lrt_km", "dist_busway_km", "dist_mall_km", "dist_hospital_km", "dist_university_km"]
FLOOD = ["flood_index"]
FLOORS = ["floors", "floors_missing"]  # floors is missing for ~12% of listings, not at random


def add_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    """Columns computed from a listing's own fields; the API builds the same ones for the house a user describes."""
    return df.assign(
        floors_missing=df.floors.isna().astype(int),
        log_land=np.log(df.land_area),
        log_building=np.log(df.building_area),
    )


def load_usable(part: str = "train") -> pd.DataFrame:
    """Usable listings with all features. part="train" for all development work; part="test" only for the final evaluation."""
    df = usable_listings()
    in_test = df.slug.isin(TEST_SLUGS.read_text(encoding="utf-8").split())
    df = df[in_test if part == "test" else ~in_test].reset_index(drop=True)
    df = add_derived_features(add_context_features(add_spatial_features(add_admin_areas(df))))
    return df.assign(
        age_days=(pd.Timestamp.now(tz="UTC") - df.created_at).dt.days,
        y=np.log(df.price / df.land_area),
    )
