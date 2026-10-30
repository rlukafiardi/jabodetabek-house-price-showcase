"""Neighbourhood context features (candidates for E18): distances to business centres, major roads, rivers, railway and power
lines, and the share of land within 500 m used for residential, commercial or industrial purposes (OSM). All in metres in
UTM zone 48S, reported in km or as shares."""

from functools import cache

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from src.config import EXTERNAL

METRIC_CRS = "EPSG:32748"
DISK_M = 500
CENTERS = {  # approximate (within about 500 m), taken from well-known malls and districts
    "scbd": (-6.2245, 106.8095), "kuningan": (-6.2297, 106.8300), "thamrin": (-6.1952, 106.8217),
    "pondok_indah": (-6.2658, 106.7841), "kelapa_gading": (-6.1578, 106.9051), "pik": (-6.1099, 106.7402),
    "bsd": (-6.3045, 106.6430), "alam_sutera": (-6.2410, 106.6560), "karawaci": (-6.2262, 106.6094),
    "cibubur": (-6.3685, 106.8940), "margonda": (-6.3731, 106.8327), "summarecon_bekasi": (-6.2263, 107.0013),
    "bogor": (-6.6013, 106.8062),
}
CBD = ["scbd", "kuningan", "thamrin"]
ROAD_CLASSES = {"dist_primary_road_km": ["motorway", "trunk", "primary"], "dist_secondary_road_km": ["secondary"], "dist_tertiary_road_km": ["tertiary"]}
LAND_USE = {"share_residential_500m": ["residential"], "share_commercial_500m": ["commercial", "retail"], "share_industrial_500m": ["industrial"]}
LINE_LAYERS = {"dist_river_km": "waterways", "dist_rail_line_km": "railway_lines", "dist_power_line_km": "power_lines"}
CONTEXT_FEATURES = ["dist_cbd_km", "dist_center_km", *ROAD_CLASSES, *LAND_USE, "dist_industrial_km", *LINE_LAYERS]


def _nearest_km(points: np.ndarray, tree: shapely.STRtree) -> np.ndarray:
    _, distance = tree.query_nearest(points, return_distance=True, all_matches=False)
    return distance / 1000


def _share(disks: np.ndarray, indexed: tuple[shapely.STRtree, np.ndarray]) -> np.ndarray:
    tree, polygons = indexed
    shares = np.zeros(len(disks))
    for i, disk in enumerate(disks):
        hits = polygons[tree.query(disk, predicate="intersects")]
        if len(hits):
            shares[i] = shapely.intersection(shapely.union_all(hits), disk).area / disk.area
    return shares


@cache
def _layers() -> dict:
    """Spatial indexes of every reference layer, built once per process (the API answers one point per request)."""
    def tree(geometries) -> shapely.STRtree:
        return shapely.STRtree(geometries.to_numpy())
    roads = gpd.read_file(EXTERNAL / "osm_roads_major.geojson").to_crs(METRIC_CRS)
    landuse = gpd.read_file(EXTERNAL / "osm_landuse.geojson").to_crs(METRIC_CRS)
    landuse["geometry"] = landuse.geometry.make_valid()  # hand-drawn OSM polygons can self-intersect
    shares = {}
    for column, classes in LAND_USE.items():
        polygons = landuse.geometry[landuse.landuse.isin(classes)].to_numpy()
        shares[column] = (shapely.STRtree(polygons), polygons)
    return {"roads": {column: tree(roads.geometry[roads.highway.isin(classes)]) for column, classes in ROAD_CLASSES.items()},
            "shares": shares, "industrial": tree(landuse.geometry[landuse.landuse == "industrial"]),
            "lines": {column: tree(gpd.read_file(EXTERNAL / f"osm_{layer}.geojson").to_crs(METRIC_CRS).geometry) for column, layer in LINE_LAYERS.items()}}


def add_context_features(df: pd.DataFrame) -> pd.DataFrame:
    points = gpd.GeoSeries(gpd.points_from_xy(df.lon, df.lat), crs="EPSG:4326").to_crs(METRIC_CRS).to_numpy()
    centers = gpd.GeoSeries(gpd.points_from_xy([c[1] for c in CENTERS.values()], [c[0] for c in CENTERS.values()]), crs="EPSG:4326").to_crs(METRIC_CRS)
    center_km = pd.DataFrame({name: shapely.distance(points, geometry) / 1000 for name, geometry in zip(CENTERS, centers)})
    features = {"dist_cbd_km": center_km[CBD].min(axis=1).to_numpy(), "dist_center_km": center_km.min(axis=1).to_numpy()}
    layers = _layers()
    for column, tree in layers["roads"].items():
        features[column] = _nearest_km(points, tree)
    disks = shapely.buffer(points, DISK_M)
    for column, indexed in layers["shares"].items():
        features[column] = _share(disks, indexed)
    features["dist_industrial_km"] = _nearest_km(points, layers["industrial"])
    for column, tree in layers["lines"].items():
        features[column] = _nearest_km(points, tree)
    return df.assign(**features)
