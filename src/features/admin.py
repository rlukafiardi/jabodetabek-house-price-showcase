from functools import cache

import geopandas as gpd
import pandas as pd

from src.config import SPATIAL


@cache
def _kecamatan() -> gpd.GeoDataFrame:
    return gpd.read_file(SPATIAL / "big_kecamatan_jabodetabek.geojson")[["kdcpum", "wadmkc", "geometry"]]  # read once per process


def add_admin_areas(df: pd.DataFrame) -> pd.DataFrame:
    points = gpd.GeoDataFrame(df[["lat", "lon"]], geometry=gpd.points_from_xy(df.lon, df.lat), crs="EPSG:4326")
    kecamatan = _kecamatan()
    in_kecamatan = points.sjoin(kecamatan, how="left", predicate="within")[["kdcpum", "wadmkc"]]
    # a point on a shared edge can match two polygons; keep the first
    return df.assign(
        kecamatan_code=in_kecamatan[~in_kecamatan.index.duplicated()].kdcpum,
        kecamatan=in_kecamatan[~in_kecamatan.index.duplicated()].wadmkc,
    )
