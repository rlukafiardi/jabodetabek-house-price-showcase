import httpx

from src.config import LAYERS_RAW as RAW

FLOOD_URL = "https://gis.bnpb.go.id/server/rest/services/inarisk/INDEKS_BAHAYA_BANJIR/ImageServer/exportImage"
FLOOD_TIF = RAW / "inarisk" / "flood_hazard.tif"
# Jabodetabek at about 30 m (0.00027 degrees), as the InaRISK to QGIS plugin requests it; the server caps the size at 4000 x 4000
PARAMS = {"bbox": "106.4,-6.8,107.3,-5.9", "bboxSR": 4326, "imageSR": 4326, "size": "3334,3334", "format": "tiff", "f": "image"}
USER_AGENT = "Mozilla/5.0 (research; personal non-commercial project; contact you@example.com)"

if __name__ == "__main__":
    FLOOD_TIF.parent.mkdir(parents=True, exist_ok=True)
    response = httpx.get(FLOOD_URL, params=PARAMS, headers={"User-Agent": USER_AGENT}, timeout=280)
    response.raise_for_status()
    assert response.headers["content-type"] == "image/tiff", response.text[:200]
    FLOOD_TIF.write_bytes(response.content)
    print(f"{len(response.content) / 1e6:.1f} MB")
