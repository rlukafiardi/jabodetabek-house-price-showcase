from functools import cache

import numpy as np
import pandas as pd
import rasterio
from sklearn.neighbors import BallTree

from src.config import EXTERNAL
from src.ingestion.inarisk import FLOOD_TIF

EARTH_RADIUS_KM = 6371.0088
MONAS = pd.DataFrame({"lat": [-6.1754], "lon": [106.8272]})
RAIL_NETWORKS = {
    "dist_krl_km": ["KAI Commuter"],
    "dist_mrt_lrt_km": ["MRT Jakarta", "LRT Jakarta", "LRT Jabodebek"],
}
POINT_LAYERS = {
    "dist_station_km": "stations",
    "dist_toll_km": "toll_booths",
    "dist_busway_km": "bus_stops",
    "dist_mall_km": "malls",
    "dist_hospital_km": "hospitals",
    "dist_university_km": "universities",
}

BUFFERS = {  # feature -> (OSM point layer, radius in km); access scales, inside the ~5 km price-similarity range from the EDA
    "n_rail_1km": ("stations", 1.0),
    "n_rail_2km": ("stations", 2.0),
    "n_busway_500m": ("bus_stops", 0.5),
    "n_busway_1km": ("bus_stops", 1.0),
    "n_mall_2km": ("malls", 2.0),
    "n_hospital_2km": ("hospitals", 2.0),
    "n_university_2km": ("universities", 2.0),
}
FLOOD_BUFFER_M = 500
BUFFER_FEATURES = list(BUFFERS) + ["flood_mean_500m"]


@cache
def _csv(layer: str) -> pd.DataFrame:
    return pd.read_csv(EXTERNAL / f"osm_{layer}.csv")  # read once per process: the API answers one point per request


@cache
def _band(path: str) -> np.ndarray:
    with rasterio.open(path) as raster:
        return raster.read(1)


def nearest_km(lat: pd.Series, lon: pd.Series, points: pd.DataFrame) -> np.ndarray:
    tree = BallTree(np.radians(points[["lat", "lon"]].to_numpy()), metric="haversine")
    distance, _ = tree.query(np.radians(np.column_stack([lat, lon])), k=1)
    return distance[:, 0] * EARTH_RADIUS_KM


def count_within_km(lat: pd.Series, lon: pd.Series, points: pd.DataFrame, radius_km: float) -> np.ndarray:
    tree = BallTree(np.radians(points[["lat", "lon"]].to_numpy()), metric="haversine")
    return tree.query_radius(np.radians(np.column_stack([lat, lon])), r=radius_km / EARTH_RADIUS_KM, count_only=True)


def raster_mean_within_m(raster, lat: pd.Series, lon: pd.Series, radius_m: float) -> np.ndarray:
    """Mean of the raster cells whose centres lie within radius_m of each point (a circular buffer)."""
    data = _band(raster.name)
    cell_m = raster.res[0] * 111_320  # degrees to metres; the cos(latitude) correction at 6 degrees south is 0.5%
    k = int(np.ceil(radius_m / cell_m))
    rows, cols = np.mgrid[-k:k + 1, -k:k + 1]
    disk = (rows ** 2 + cols ** 2) * cell_m ** 2 <= radius_m ** 2
    means = []
    for la, lo in zip(lat, lon):
        r, c = raster.index(lo, la)
        window = data[r - k:r + k + 1, c - k:c + k + 1]
        means.append(window[disk].mean() if window.shape == disk.shape else np.nan)  # nan only at the raster edge
    return np.array(means)


def add_spatial_features(df: pd.DataFrame) -> pd.DataFrame:
    at_district_centroid = (df.lat.round(6) == df.district_lat.round(6)) & (df.lon.round(6) == df.district_lon.round(6))
    features = {"coord_is_centroid": at_district_centroid.astype(int), "dist_monas_km": nearest_km(df.lat, df.lon, MONAS)}
    stations = _csv("stations")
    for column, networks in RAIL_NETWORKS.items():
        features[column] = nearest_km(df.lat, df.lon, stations[stations.network.isin(networks)])
    for column, layer in POINT_LAYERS.items():
        features[column] = nearest_km(df.lat, df.lon, _csv(layer))
    with rasterio.open(FLOOD_TIF) as flood:
        features["flood_index"] = np.array([v[0] for v in flood.sample(zip(df.lon, df.lat))])
        features["flood_mean_500m"] = raster_mean_within_m(flood, df.lat, df.lon, FLOOD_BUFFER_M)
    layers = {layer: _csv(layer) for layer, _ in BUFFERS.values()}
    for column, (layer, radius_km) in BUFFERS.items():
        features[column] = count_within_km(df.lat, df.lon, layers[layer], radius_km)
    return df.assign(**features)
