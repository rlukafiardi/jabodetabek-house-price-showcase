import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
# Crawl state (raw pages, sitemaps, plans, parsed listings, slug lists): data/ locally, the mounted bucket in the pipeline jobs (STATE_DIR)
STATE = Path(os.environ.get("STATE_DIR", DATA))
RAW = STATE / "raw"
INTERIM = STATE / "interim"
PROCESSED = STATE / "processed"
PORTAL_RAW = RAW / "portal"
# Reference layers ship with the code (the API image), never with the state
LAYERS_RAW = DATA / "raw"
EXTERNAL = DATA / "external"
SPATIAL = DATA / "spatial"
