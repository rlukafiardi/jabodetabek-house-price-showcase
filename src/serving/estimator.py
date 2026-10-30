"""Price estimate for one house described by a user: builds the model's features with the same functions as training (src/features,
dataset.add_derived_features, parse.text_flags), scores the three ensemble members and the text model, and adds the range. The
reference layers and models load once per process. Differences from training, all deliberate: the point is the user's own (never a
district centroid), age_days is the freshest training listing, the text score is clipped to the training range, and no land title is used."""

from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.features.admin import add_admin_areas
from src.features.context import add_context_features
from src.features.spatial import add_spatial_features
from src.ingestion.parse import clean_words, text_flags
from src.modeling.dataset import add_derived_features
from src.modeling.intervals import LARGE_PLOT_M2, apply_range

# What the explanation names: each group of inputs is swapped for the typical house's values and the estimate re-run (the change is the group's effect)
LOCATION = ["lat", "lon", "coord_is_centroid", "dist_station_km", "dist_monas_km", "dist_krl_km", "dist_mrt_lrt_km", "dist_busway_km", "dist_cbd_km", "dist_center_km"]
SURROUNDINGS = ["dist_primary_road_km", "dist_secondary_road_km", "dist_tertiary_road_km", "share_residential_500m", "share_commercial_500m", "share_industrial_500m",
                "dist_industrial_km", "dist_river_km", "dist_rail_line_km", "dist_power_line_km", "flood_index"]
FACTOR_LABELS = {"location": "Location and transport", "surroundings": "Surroundings", "land": "Land area", "building": "Building area", "rooms": "Bedrooms and bathrooms",
                 "floors": "Floors", "notes": "The notes", "details": "The optional details"}
FACTOR_MIN_EFFECT = 0.03  # smaller effects are not worth naming
FACTOR_TOP = 4

SPEC_COLUMNS = ["spec_electricity_va", "spec_carport", "spec_car_access", "spec_garage", "spec_maid_rooms", "spec_furnished_level", "spec_water_pam"]


@dataclass
class House:
    lat: float
    lon: float
    land_area: float
    building_area: float
    bedrooms: int
    bathrooms: int
    floors: float | None = None
    notes: str = ""
    specs: dict[str, float] = field(default_factory=dict)  # any of SPEC_COLUMNS; absent means unknown


class OutsideArea(ValueError):
    """The point is not inside a Jabodetabek kecamatan."""


class Estimator:
    def __init__(self, model_dir: Path):
        self.bundle = joblib.load(model_dir / "model.joblib")
        self.columns: list[str] = self.bundle["columns"]
        self.estimate(House(lat=-6.2, lon=106.82, land_area=100, building_area=100, bedrooms=3, bathrooms=2))  # builds the layer indexes now, not on the first request

    def factor_groups(self) -> dict[str, list[str]]:
        notes = [c for c in self.columns if c.startswith("txt_")] + ["text_score"]
        return {"location": LOCATION, "surroundings": SURROUNDINGS, "land": ["log_land"], "building": ["log_building"], "rooms": ["bedrooms", "bathrooms"],
                "floors": ["floors", "floors_missing"], "notes": notes, "details": [c for c in self.columns if c.startswith("spec_")]}

    def factors(self, x: pd.DataFrame, house: House) -> list[dict]:
        """What moves the price per m² of land compared with a typical house in the data, biggest first. Groups the user left empty are not named
        (their effect would only be the effect of not knowing). Approximate: inputs are correlated, so the effects are not additive."""
        reference = self.bundle.get("reference")
        if reference is None:
            return []
        left_out = {"notes": not house.notes.strip(), "details": not house.specs, "floors": house.floors is None}
        groups = {name: cols for name, cols in self.factor_groups().items() if not left_out.get(name)}
        batch = pd.concat([x] * (len(groups) + 1), ignore_index=True)
        for i, cols in enumerate(groups.values(), start=1):
            batch.loc[i, cols] = reference[cols].to_numpy()
        log_price = np.mean([m.predict(batch) for m in self.bundle["parts"].values()], axis=0)
        effects = np.expm1(log_price[0] - log_price[1:])
        ranked = sorted(zip(groups, effects), key=lambda pair: -abs(pair[1]))
        return [{"code": name, "effect": round(float(effect), 3), "label": FACTOR_LABELS[name]} for name, effect in ranked if abs(effect) >= FACTOR_MIN_EFFECT][:FACTOR_TOP]

    @property
    def info(self) -> dict:
        return self.bundle["info"]

    def features(self, house: House) -> pd.DataFrame:
        specs = {column: house.specs.get(column, np.nan) for column in SPEC_COLUMNS}
        row = pd.DataFrame([{"lat": house.lat, "lon": house.lon, "district_lat": np.nan, "district_lon": np.nan, "land_area": house.land_area,
                             "building_area": house.building_area, "bedrooms": house.bedrooms, "bathrooms": house.bathrooms,
                             "floors": np.nan if house.floors is None else house.floors, **specs}])
        row = add_context_features(add_spatial_features(add_admin_areas(add_derived_features(row))))
        if pd.isna(row.kecamatan_code.iloc[0]):
            raise OutsideArea("The point is outside Jabodetabek.")
        notes = house.notes.lower()
        return row.assign(**text_flags(notes), age_days=self.bundle["age_days"], words=clean_words(notes))

    def estimate(self, house: House) -> dict:
        row = self.features(house)
        score = float(np.clip(self.bundle["text_model"].predict(row.words)[0], *self.bundle["text_score_range"]))
        x = row.assign(text_score=score)[self.columns]
        per_m2 = float(np.exp(np.mean([m.predict(x)[0] for m in self.bundle["parts"].values()])))
        price = per_m2 * house.land_area
        city = self.bundle["city_by_code"].get(str(row.kecamatan_code.iloc[0])[:4])
        ranges = {}
        for name, column in (("possible", ""), ("likely", "_50")):
            low, high = apply_range(np.array([price]), pd.Series([city]), self.bundle["ranges"], column, row.land_area)
            ranges[name] = [float(low[0]), float(high[0])]
        warnings = []  # a code for the page to translate, and the English message for other clients
        if house.land_area > LARGE_PLOT_M2:
            warnings.append({"code": "large_plot", "message": f"Plots over {LARGE_PLOT_M2} m² are priced less predictably, so the ranges are wider."})
        if row.txt_take_over.iloc[0]:
            warnings.append({"code": "take_over", "message": "Take-over (over kredit) listings quote a transfer fee, not the house value; this estimate does not apply to them."})
        if row.txt_auction.iloc[0]:
            warnings.append({"code": "auction", "message": "Auction listings tend to ask less than the market price; the estimate may be too high."})
        return {"price_idr": round(price), "price_per_m2_land_idr": round(per_m2), "likely_range_idr": [round(v) for v in ranges["likely"]],
                "possible_range_idr": [round(v) for v in ranges["possible"]],
                "area": {"kecamatan": row.kecamatan.iloc[0], "city": city}, "text_score_used": bool(house.notes.strip()), "warnings": warnings,
                "factors": self.factors(x, house)}
