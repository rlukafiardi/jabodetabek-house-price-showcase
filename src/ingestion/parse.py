import gzip
import json
import re

import pandas as pd
from selectolax.lexbor import LexborHTMLParser

from src.config import INTERIM, PORTAL_RAW

# Keys dropped before a page is stored: agent contact data, photos and a wishlist id. Nothing else in the block is personal.
DROP_KEYS = ("owner", "listing", "photoURLs", "photos360", "wishlistGuid")
COORDINATE = re.compile(r"\(([-\d.]+),([-\d.]+)\)")
# Keyword flags from the listing title and description. Only the flags are kept: descriptions can hold agent phone numbers.
TEXT_FLAGS = {
    "txt_take_over": r"take ?over|over ?kredit|oper ?kredit|alih ?kredit|lanjut ?(kpr|cicilan|kredit)",
    "txt_auction": r"\blelang\b",
    "txt_land_value": r"hitung tanah|harga tanah|hrg tanah",
    "txt_needs_work": r"rumah tua|bangunan tua|bangunan lama|butuh renovasi|perlu renovasi|perlu perbaikan",
    "txt_new": r"rumah baru|bangunan baru|brand new|baru gres|baru gress|baru selesai renovasi|full renov",
    "txt_luxury": r"mewah|luxury|premium|elegan|private pool|kolam renang",
    "txt_furnished": r"furnish|full perabot",
    "txt_corner": r"\bhook\b|\bhoek\b|\bsudut\b",
    "txt_gated": r"cluster|one gate|komplek elit|perumahan elit",
    "txt_wide_road": r"(jalan|akses) (2|dua) mobil|jalan lebar",
    "txt_commercial": r"cocok (untuk )?usaha|cocok (untuk )?kantor|\bkost?\b|kos-kosan|kontrakan",
    "txt_urgent": r"butuh uang|jual cepat|turun harga|di ?bawah (harga )?pasar|di ?bawah njop",
    "txt_flood_free": r"bebas banjir",
}


# Spec and facility fields from specsAndFacilities (about 57 keys; the ones below appear in at least 10% of listings).
SPEC_NUMERIC = {"spec_electricity_va": "specifications.electricity",  # total_toilet is not kept: it always equals bathrooms
                "spec_carport": "specifications.carport_capacity", "spec_car_access": "specifications.car_access_capacity",
                "spec_garage": "specifications.garage_capacity", "spec_maid_rooms": "specifications.total_household_assistant_room"}
FACILITY_FLAGS = ["full_presence_security", "air_conditioner", "kitchen_set", "garden", "balcony", "swimming_pool", "gym",
                  "elevator", "cctv", "jogging_track", "water_heater", "public_swimming_pool"]
SPEC_FEATURES = [*SPEC_NUMERIC, "spec_furnished_level", "spec_water_pam", "fac_count", *(f"fac_{name}" for name in FACILITY_FLAGS)]

TEXT_FILE = INTERIM / "portal_text.csv"  # slug + cleaned words for the text model; gitignored, never printed


def listing_text(d: dict) -> str:
    description = LexborHTMLParser(d.get("description") or "").text(separator=" ")
    return f"{d.get('title') or ''} {description}".lower()


def clean_words(text: str) -> str:
    """Letters-only words of 3+ characters, with emails and URLs removed, so phone numbers and addresses cannot get in."""
    text = re.sub(r"\S+@\S+|https?://\S+|www\.\S+", " ", text.lower())
    return " ".join(re.findall(r"[a-z]{3,}", text))


def text_flags(text: str) -> dict[str, int]:
    return {name: int(re.search(pattern, text) is not None) for name, pattern in TEXT_FLAGS.items()}


def extract_detail(html: str) -> dict | None:
    """The __UNIT_DETAIL__ block of a listing page without the keys in DROP_KEYS; None if the page has no such block."""
    script = LexborHTMLParser(html).css_first("script#__UNIT_DETAIL__")
    if script is None:
        return None
    return {k: v for k, v in json.loads(script.text()).items() if k not in DROP_KEYS}


def write_detail(path, detail: dict | None) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as file:
        json.dump(detail, file, ensure_ascii=False)


def spec_features(d: dict) -> dict:
    """Numeric specs (missing when absent), furnished level 0-2, water source, facility flags (absent counts as 0) and their count."""
    spec = {item["localeKey"]: item["value"] for item in d.get("specsAndFacilities") or []}
    numeric = {name: pd.to_numeric(spec.get(key), errors="coerce") for name, key in SPEC_NUMERIC.items()}
    furnished = str(spec.get("specifications.property_furnished_condition", ""))
    water = spec.get("specifications.water_source")
    ticked = {key for key, value in spec.items() if key.startswith("facilities.") and str(value).lower() == "true"}  # the API sends "true" as a string
    flags = {f"fac_{name}": int(f"facilities.{name}" in ticked) for name in FACILITY_FLAGS}
    return {**numeric,
            "spec_furnished_level": {"non_furnished": 0, "semi_furnished": 1, "furnished": 2}.get(furnished.split(".")[-1], float("nan")),
            "spec_water_pam": {"PAM": 1, "Air Tanah": 0}.get(water, float("nan")),
            "fac_count": len(ticked), **flags}


def parse_detail(d: dict) -> dict:
    specs = d["specs"]
    district = d["district"]
    district_lat, district_lon = map(float, COORDINATE.match(district["coordinate"]).groups()) if district else (None, None)
    return {
        "slug": d["slug"],
        "building_type": d["buildingType"],
        "price": d["minPrice"],
        "price_max": d["maxPrice"],
        "land_area": specs.get("surfaceArea"),
        "building_area": specs.get("buildingArea"),
        "bedrooms": specs.get("bedroom"),
        "bathrooms": specs.get("restroom"),
        "floors": specs.get("numberOfFloor"),
        "certificate": specs.get("certificate"),
        "province": d["province"]["title"],
        "city": d["city"]["title"],
        "district": district["title"] if district else None,
        "sub_district": d["subDistrict"]["title"] if d["subDistrict"] else None,
        "lat": d["coordinate"][0],
        "lon": d["coordinate"][1],
        "district_lat": district_lat,
        "district_lon": district_lon,
        "created_at": d["createdAt"],
        "status": d["status"].split(".")[-1],
        "on_market": d["onMarket"],
        **text_flags(listing_text(d)),
        **spec_features(d),
        "words": clean_words(listing_text(d)),
    }


def parse_all() -> tuple[pd.DataFrame, int]:
    files = sorted(PORTAL_RAW.glob("*.json.gz"))
    details = []
    for f in files:
        with gzip.open(f, "rt", encoding="utf-8") as file:
            details.append(json.load(file))
    parsed = [parse_detail(d) for d in details if d is not None]
    return pd.DataFrame(parsed), len(files) - len(parsed)


if __name__ == "__main__":
    df, unparsed = parse_all()
    INTERIM.mkdir(parents=True, exist_ok=True)
    df.drop(columns="words").to_csv(INTERIM / "portal_listings.csv", index=False)
    df[["slug", "words"]].to_csv(TEXT_FILE, index=False)
    print(f"{len(df)} parsed, {unparsed} without __UNIT_DETAIL__")
