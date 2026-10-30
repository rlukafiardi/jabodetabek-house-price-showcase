import pandas as pd

from src.ingestion.validate import hard_failures, soft_flags


def listings(**changes) -> pd.DataFrame:
    row = {"slug": "a", "price": 1e9, "price_max": 1e9, "land_area": 100, "building_area": 90, "bedrooms": 3, "bathrooms": 2, "city": "Kota Bekasi",
           "lat": -6.25, "lon": 107.0, "created_at": pd.Timestamp("2026-06-01"), "status": "active", "on_market": True}
    return pd.DataFrame([{**row, **changes}])


def test_clean_row_passes():
    assert hard_failures(listings()) == [] and soft_flags(listings()) == {}


def test_missing_column_is_a_hard_failure():
    assert hard_failures(listings().drop(columns="price")) == ["missing column price"]


def test_nulls_and_non_positive_values_are_hard_failures():
    assert hard_failures(listings(land_area=None))
    assert hard_failures(listings(price=0))


def test_duplicate_slugs_are_hard_failures():
    assert hard_failures(pd.concat([listings(), listings()]))


def test_out_of_range_values_are_flagged_not_failed():
    df = listings(price=5e10, land_area=6000)
    assert hard_failures(df) == []
    assert len(soft_flags(df)) == 2
