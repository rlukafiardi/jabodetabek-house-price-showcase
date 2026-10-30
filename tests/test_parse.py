import json

import pandas as pd

from src.ingestion.parse import DROP_KEYS, clean_words, extract_detail, parse_detail, spec_features, text_flags

DETAIL = {
    "slug": "dijual-rumah-contoh", "buildingType": "house", "minPrice": 1_500_000_000, "maxPrice": 1_500_000_000,
    "specs": {"surfaceArea": 100, "buildingArea": 120, "bedroom": 3, "restroom": 2, "numberOfFloor": 2, "certificate": "SHM"},
    "province": {"title": "DKI Jakarta"}, "city": {"title": "Kota Jakarta Selatan"},
    "district": {"title": "Tebet", "coordinate": "(-6.23,106.85)"}, "subDistrict": {"title": "Tebet Barat"},
    "coordinate": [-6.231, 106.851], "createdAt": "2026-06-01T00:00:00Z", "status": "ListingStatus.active", "onMarket": True,
    "title": "Rumah mewah cluster bebas banjir", "description": "<p>Hubungi 0812-3456-7890 atau agen@contoh.com</p>",
    "specsAndFacilities": [{"localeKey": "specifications.electricity", "value": "2200"},
                           {"localeKey": "facilities.garden", "value": "true"}, {"localeKey": "facilities.gym", "value": "false"}],
    "owner": {"name": "Agen", "phone": "0812"}, "photoURLs": ["a.jpg"], "listing": {"x": 1}, "photos360": [], "wishlistGuid": "g",
}


def page(detail: dict) -> str:
    return f'<html><script id="__UNIT_DETAIL__" type="application/json">{json.dumps(detail)}</script></html>'


def test_extract_detail_drops_personal_and_photo_keys():
    detail = extract_detail(page(DETAIL))
    assert not set(DROP_KEYS) & set(detail)
    assert detail["slug"] == "dijual-rumah-contoh"


def test_extract_detail_without_block_is_none():
    assert extract_detail("<html><body>no data</body></html>") is None


def test_clean_words_removes_phone_numbers_emails_and_urls():
    words = clean_words("Hubungi 0812-3456-7890 agen@contoh.com https://contoh.com rumah bagus")
    assert words == "hubungi rumah bagus"


def test_text_flags():
    flags = text_flags("rumah mewah di cluster, bebas banjir, jual cepat")
    assert flags["txt_luxury"] == flags["txt_gated"] == flags["txt_flood_free"] == flags["txt_urgent"] == 1
    assert flags["txt_take_over"] == flags["txt_auction"] == 0


def test_take_over_variants_are_flagged():
    assert all(text_flags(t)["txt_take_over"] for t in ["over kredit", "take over", "lanjut kpr"])


def test_spec_features_parse_strings_and_count_ticked_facilities():
    spec = spec_features(DETAIL)
    assert spec["spec_electricity_va"] == 2200
    assert spec["fac_garden"] == 1 and spec["fac_gym"] == 0 and spec["fac_count"] == 1
    assert pd.isna(spec["spec_carport"])


def test_parse_detail_core_fields_and_no_raw_text():
    row = parse_detail(extract_detail(page(DETAIL)))
    assert (row["price"], row["land_area"], row["building_area"], row["status"]) == (1_500_000_000, 100, 120, "active")
    assert row["district_lat"] == -6.23 and row["txt_luxury"] == 1
    assert "0812" not in row["words"] and "contoh" not in row["words"]  # digits and e-mail never reach the text column
