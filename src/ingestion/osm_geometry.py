"""OSM lines and polygons (major roads, land use, rivers, railway lines, power lines) for the Jabodetabek box, fetched in tiles
so each Overpass request stays small, saved as GeoJSON in data/external/. Same politeness as osm.py (identifying User-Agent,
a pause between requests, retries with backoff on 5xx and 429, stop if it still fails). A layer already on disk is skipped."""

import time

import geopandas as gpd
import httpx
from shapely.geometry import LineString, Polygon

from src.config import EXTERNAL
from src.ingestion.osm import OVERPASS_URL, PAUSE_SECONDS, USER_AGENT

SOUTH, WEST, NORTH, EAST = -6.8, 106.4, -5.9, 107.3
RETRY_WAITS = (30, 60, 120)
LAYERS = {  # layer -> (Overpass filter, geometry type, tiles per side)
    "roads_major": ('way["highway"~"^(motorway|trunk|primary|secondary|tertiary)$"]', "line", 3),
    "landuse": ('way["landuse"~"^(residential|commercial|retail|industrial)$"]', "polygon", 6),
    "waterways": ('way["waterway"~"^(river|canal)$"]', "line", 3),
    "railway_lines": ('way["railway"="rail"]', "line", 3),
    "power_lines": ('way["power"="line"]', "line", 3),
}
TAGS = ("highway", "landuse", "waterway", "railway", "power", "name")


def tiles(per_side: int) -> list[str]:
    lats = [SOUTH + (NORTH - SOUTH) * i / per_side for i in range(per_side + 1)]
    lons = [WEST + (EAST - WEST) * i / per_side for i in range(per_side + 1)]
    return [f"{lats[i]},{lons[j]},{lats[i + 1]},{lons[j + 1]}" for i in range(per_side) for j in range(per_side)]


def fetch(filter_: str, bbox: str, kind: str) -> list[dict]:
    query = f"[out:json][timeout:120];{filter_}({bbox});out geom;"
    for wait in (*RETRY_WAITS, None):
        try:
            response = httpx.post(OVERPASS_URL, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=150)
        except httpx.TransportError as error:
            if wait is None:
                raise
            print(f"{error!r} for tile {bbox}, retrying in {wait}s", flush=True)
            time.sleep(wait)
            continue
        if (response.status_code < 500 and response.status_code != 429) or wait is None:
            break
        print(f"{response.status_code} for tile {bbox}, retrying in {wait}s", flush=True)
        time.sleep(wait)
    response.raise_for_status()
    rows = []
    for element in response.json()["elements"]:
        points = [(p["lon"], p["lat"]) for p in element.get("geometry", [])]
        if kind == "line" and len(points) >= 2:
            geometry = LineString(points)
        elif kind == "polygon" and len(points) >= 4 and points[0] == points[-1]:
            geometry = Polygon(points)
        else:
            continue
        rows.append({"osm_id": element["id"], **{k: element["tags"].get(k) for k in TAGS}, "geometry": geometry})
    return rows


if __name__ == "__main__":
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    for layer, (filter_, kind, per_side) in LAYERS.items():
        if (EXTERNAL / f"osm_{layer}.geojson").exists():
            continue
        rows = []
        for bbox in tiles(per_side):
            rows += fetch(filter_, bbox, kind)
            time.sleep(PAUSE_SECONDS)
        gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326").drop_duplicates("osm_id")  # a way crossing a tile edge comes back from both tiles
        gdf.to_file(EXTERNAL / f"osm_{layer}.geojson", driver="GeoJSON")
        print(layer, len(gdf), flush=True)
