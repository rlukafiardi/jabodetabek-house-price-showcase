import sys

import pandas as pd

from src.config import INTERIM
from src.modeling.split import DUPLICATE_KEY, JABODETABEK, LAT_RANGE, LON_RANGE, MAX_ROOMS

REQUIRED = ["slug", "price", "land_area", "building_area", "bedrooms", "bathrooms", "city", "lat", "lon", "created_at", "status", "on_market"]
POSITIVE = ["price", "land_area", "building_area"]
# soft limits: rows outside are reported, not dropped
SOFT_LIMITS = {
    "price": (1e8, 1e11),  # 100 million to 100 billion IDR
    "land_area": (15, 5000),
    "building_area": (15, 3000),
    "bedrooms": (1, 15),
    "bathrooms": (1, 15),
    "lat": LAT_RANGE,
    "lon": LON_RANGE,
}


def hard_failures(df: pd.DataFrame) -> list[str]:
    problems = [f"missing column {c}" for c in REQUIRED if c not in df.columns]
    if problems:
        return problems
    problems += [f"{c} has {int(df[c].isna().sum())} nulls" for c in REQUIRED if df[c].isna().any()]
    problems += [f"{c} has {int((df[c] <= 0).sum())} values <= 0" for c in POSITIVE if (df[c] <= 0).any()]
    if df.slug.duplicated().any():
        problems.append(f"{int(df.slug.duplicated().sum())} duplicate slugs")
    return problems


def soft_flags(df: pd.DataFrame) -> dict[str, int]:
    flags = {f"{c} outside [{lo:g}, {hi:g}]": int(((df[c] < lo) | (df[c] > hi)).sum()) for c, (lo, hi) in SOFT_LIMITS.items()}
    flags["price_max != price"] = int((df.price != df.price_max).sum())
    return {k: v for k, v in flags.items() if v}


def waterfall(df: pd.DataFrame) -> list[tuple[str, int]]:
    steps = [("parsed pages", len(df))]
    df = df[df.city.str.contains(JABODETABEK)]
    steps.append(("city in Jabodetabek", len(df)))
    df = df[(df.status == "active") & df.on_market]
    steps.append(("active and on market", len(df)))
    df = df.sort_values("slug").drop_duplicates(DUPLICATE_KEY)
    steps.append(("after removing exact duplicates", len(df)))
    df = df[df.lat.between(*LAT_RANGE) & df.lon.between(*LON_RANGE)]
    steps.append(("coordinates inside the Jabodetabek bounding box", len(df)))
    df = df[(df.bedrooms <= MAX_ROOMS) & (df.bathrooms <= MAX_ROOMS)]
    steps.append((f"at most {MAX_ROOMS} bedrooms and bathrooms", len(df)))
    df = df[df.txt_take_over == 0]
    steps.append(("not a take-over (over kredit) listing", len(df)))
    return steps


if __name__ == "__main__":
    df = pd.read_csv(INTERIM / "portal_listings.csv")
    for name, n in waterfall(df):
        print(f"{n:6d}  {name}")
    for flag, n in soft_flags(df).items():
        print(f"flag: {flag}: {n}")
    problems = hard_failures(df)
    if problems:
        sys.exit("FAILED: " + "; ".join(problems))
    print("hard checks passed")
