import time

import httpx
import pandas as pd

from src.config import EXTERNAL

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "jabodetabek-house-price (personal non-commercial research; you@example.com)"
BBOX = "-6.8,106.4,-5.9,107.3"  # south, west, north, east: covers Jabodetabek
QUERIES = {
    "stations": f'node["railway"="station"]({BBOX});',
    "toll_booths": f'node["barrier"="toll_booth"]({BBOX});',
    "bus_stops": f'nwr["highway"="bus_stop"]["network"~"Trans",i]({BBOX});',
    "malls": f'nwr["shop"="mall"]({BBOX});',
    "hospitals": f'nwr["amenity"="hospital"]({BBOX});',
    "universities": f'nwr["amenity"="university"]({BBOX});',
}
PAUSE_SECONDS = 5  # the public Overpass server is shared; keep requests spaced


def fetch_points(query: str) -> pd.DataFrame:
    response = httpx.post(OVERPASS_URL, data={"data": f"[out:json][timeout:60];{query}out center;"}, headers={"User-Agent": USER_AGENT}, timeout=90)
    response.raise_for_status()
    return pd.DataFrame(
        [{"osm_id": e["id"], "lat": e.get("lat") or e["center"]["lat"], "lon": e.get("lon") or e["center"]["lon"], "name": e["tags"].get("name"), **{k: e["tags"].get(k) for k in ("station", "network")}}
         for e in response.json()["elements"]]
    )


if __name__ == "__main__":
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    for name, query in QUERIES.items():
        df = fetch_points(query)
        df.to_csv(EXTERNAL / f"osm_{name}.csv", index=False)
        print(name, len(df))
        time.sleep(PAUSE_SECONDS)
