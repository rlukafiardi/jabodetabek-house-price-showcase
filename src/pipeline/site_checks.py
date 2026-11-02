"""Checks on the public site data, shared by the showcase export (scripts/publish.py) and the automatic site refresh (src/pipeline/site.py).
The data must be aggregates (known properties only, no price for an area under the minimum), and a refresh must not look worse than what is live."""

import json
from pathlib import Path

from src.features.aggregate import MIN_LISTINGS

SITE_KEYS = {"code", "name", "city", "n", "median", "p25", "p75", "cls", "mixed"}  # the only properties the site data may carry
LAYER_KEYS = {"name", "kind"}  # the map layers (public OpenStreetMap places and lines) carry nothing else
SHRINK_MIN = 0.9  # fewer priced areas or H3 cells than 90% of what is live is a bad refresh
MEDIAN_MOVE_MAX = 0.15  # the overall median price moving more than 15% in a month is a bad refresh, not a market


def data_problems(data_dir: Path) -> list[str]:
    """The site data must be aggregates: known properties only, and no price for an area under the minimum (or any such H3 cell)."""
    problems = []
    for name in ("kecamatan", "h3"):
        for feature in json.loads((data_dir / f"{name}.geojson").read_text(encoding="utf-8"))["features"]:
            props = feature["properties"]
            if set(props) - SITE_KEYS:
                problems.append(f"{name}: unexpected properties {sorted(set(props) - SITE_KEYS)}")
            if props.get("n", 0) < MIN_LISTINGS and (name == "h3" or props.get("median") is not None):
                problems.append(f"{name}: an area with {props.get('n')} listings carries a price or is published")
    for path in sorted(data_dir.glob("layer_*.geojson")):
        for feature in json.loads(path.read_text(encoding="utf-8"))["features"]:
            if set(feature["properties"]) - LAYER_KEYS:
                problems.append(f"{path.name}: unexpected properties {sorted(set(feature['properties']) - LAYER_KEYS)}")
                break
    return problems[:10]


def guard_problems(new: dict, live: dict) -> list[str]:
    """Reasons not to publish a refresh, from the two meta.json files (the new one and the one that is live)."""
    problems = []
    if new["listings_total"] < live["listings_total"]:
        problems.append(f"fewer listings than live ({new['listings_total']} against {live['listings_total']})")
    for key, label in (("kecamatan_shown", "priced kecamatan"), ("h3_cells", "H3 cells")):
        if new[key] < SHRINK_MIN * live[key]:
            problems.append(f"{label} fell from {live[key]} to {new[key]}")
    move = new["overall"]["median"] / live["overall"]["median"] - 1
    if abs(move) > MEDIAN_MOVE_MAX:
        problems.append(f"the overall median price per m² moved {move:+.0%} ({live['overall']['median']} to {new['overall']['median']} million)")
    return problems
