import sys

import pandas as pd
from sklearn.model_selection import StratifiedKFold

from src.config import INTERIM, PROCESSED

JABODETABEK = "Jakarta|Tangerang|Bekasi|Depok|Bogor"
TEST_SLUGS = PROCESSED / "test_slugs.txt"  # current holdout (v2); gitignored; written once, never regenerated
FROZEN_V1 = PROCESSED / "frozen_v1_slugs.txt"  # every usable slug at the first data freeze; the v2 holdout comes from newer rows only
SEED = 20261029
MAX_ROOMS = 8  # more bedrooms or bathrooms means a boarding house, guesthouse or office: out of scope
DUPLICATE_KEY = ["price", "land_area", "building_area", "district"]
LAT_RANGE, LON_RANGE = (-6.8, -5.9), (106.4, 107.3)  # Jabodetabek bounding box; coordinates outside it are errors


def usable_listings() -> pd.DataFrame:
    df = pd.read_csv(INTERIM / "portal_listings.csv", parse_dates=["created_at"])
    df = df[df.city.str.contains(JABODETABEK) & (df.status == "active") & df.on_market]
    # the same house listed by several agents: keep the first slug alphabetically
    df = df.sort_values("slug").drop_duplicates(DUPLICATE_KEY)
    df = df[df.lat.between(*LAT_RANGE) & df.lon.between(*LON_RANGE)]
    df = df[(df.bedrooms <= MAX_ROOMS) & (df.bathrooms <= MAX_ROOMS)]
    # take-over ("over kredit") listings quote the fee for taking over a mortgage, not the house value: out of scope
    return df[df.txt_take_over == 0].reset_index(drop=True)


def new_since_v1(df: pd.DataFrame) -> pd.DataFrame:
    return df[~df.slug.isin(FROZEN_V1.read_text(encoding="utf-8").split())].reset_index(drop=True)


def carve_test(df: pd.DataFrame) -> list[str]:
    """About 20% of the listings given, stratified by city."""
    _, test_idx = next(StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED).split(df, df.city))
    return sorted(df.slug.iloc[test_idx])


if __name__ == "__main__":
    all_usable = usable_listings()
    df = new_since_v1(all_usable)
    test = carve_test(df)
    print(f"{len(all_usable)} usable after de-duplication, {len(df)} of them new since the v1 freeze, holdout would be {len(test)}")
    print(df.assign(test=df.slug.isin(test)).groupby("city").test.agg(["size", "sum"]).to_string())
    if "--write" in sys.argv:
        if TEST_SLUGS.exists():
            sys.exit(f"{TEST_SLUGS} already exists; the test set is never regenerated")
        PROCESSED.mkdir(parents=True, exist_ok=True)
        TEST_SLUGS.write_text("\n".join(test), encoding="utf-8")
        print(f"wrote {TEST_SLUGS}")
