import h3
import pandas as pd

from src.config import ROOT
from src.features.admin import add_admin_areas
from src.modeling.split import usable_listings

MIN_LISTINGS = 5
TABLE = ROOT / "reports" / "tables" / "kecamatan_prices.csv"
H3_TABLE = ROOT / "reports" / "tables" / "h3_prices.csv"
H3_RESOLUTION = 7  # cells of about 5 km²; resolution 8 is too sparse (38% of listings in a cell with 5+)


def all_usable() -> pd.DataFrame:
    """Every usable listing, train and holdout alike: the aggregates describe the market, they are not model scores."""
    return add_admin_areas(usable_listings())


def kecamatan_prices(df: pd.DataFrame, min_listings: int = MIN_LISTINGS) -> pd.DataFrame:
    """One row per BIG kecamatan; the price columns stay empty where there are fewer than min_listings listings."""
    df = df.assign(ppm2_land=df.price / df.land_area, ppm2_building=df.price / df.building_area)
    grouped = df.groupby(["kecamatan_code", "kecamatan"])
    table = grouped.agg(
        city=("city", lambda s: s.mode().iloc[0]),
        listings=("price", "size"),
        median_ppm2_land=("ppm2_land", "median"),
        p25_ppm2_land=("ppm2_land", lambda s: s.quantile(0.25)),
        p75_ppm2_land=("ppm2_land", lambda s: s.quantile(0.75)),
        median_ppm2_building=("ppm2_building", "median"),
    ).reset_index()
    price_columns = [c for c in table if c.endswith(("land", "building"))]
    table.loc[table.listings < min_listings, price_columns] = pd.NA
    return table.sort_values("median_ppm2_land", ascending=False)


def h3_prices(df: pd.DataFrame, resolution: int = H3_RESOLUTION, min_listings: int = MIN_LISTINGS) -> pd.DataFrame:
    """One row per H3 cell with listings; price columns empty below min_listings. Listings at their district centroid are left out:
    they carry no location of their own and would all fall into one arbitrary cell."""
    own = df[(df.lat.round(6) != df.district_lat.round(6)) | (df.lon.round(6) != df.district_lon.round(6))]
    own = own.assign(cell=[h3.latlng_to_cell(a, b, resolution) for a, b in zip(own.lat, own.lon)],
                     ppm2_land=own.price / own.land_area, ppm2_building=own.price / own.building_area)
    table = own.groupby("cell").agg(
        listings=("price", "size"),
        median_ppm2_land=("ppm2_land", "median"),
        p25_ppm2_land=("ppm2_land", lambda s: s.quantile(0.25)),
        p75_ppm2_land=("ppm2_land", lambda s: s.quantile(0.75)),
        median_ppm2_building=("ppm2_building", "median"),
    ).reset_index()
    price_columns = [c for c in table if c.endswith(("land", "building"))]
    table.loc[table.listings < min_listings, price_columns] = pd.NA
    return table


if __name__ == "__main__":
    table = kecamatan_prices(all_usable())
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    table.round(0).to_csv(TABLE, index=False)
    shown = table.median_ppm2_land.notna()
    cells = h3_prices(all_usable())
    cells.round(0).to_csv(H3_TABLE, index=False)
    print(f"{cells.median_ppm2_land.notna().sum()} H3 cells (resolution {H3_RESOLUTION}) with at least {MIN_LISTINGS} listings")
    print(f"{shown.sum()} kecamatan with at least {MIN_LISTINGS} listings, covering {table.listings[shown].sum() / table.listings.sum():.0%} of {table.listings.sum():,} listings")
