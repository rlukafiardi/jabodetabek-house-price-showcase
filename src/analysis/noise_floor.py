"""How much do asking prices of the same house differ? Listings with the same district, land area, building area and rooms are
treated as one house (or identical units of one cluster) and their price gaps give a rough floor for the error of any model that
only sees these attributes. Training part only. Writes reports/tables/noise_floor.csv."""

import itertools

import numpy as np
import pandas as pd

from src.config import INTERIM, ROOT
from src.modeling.split import JABODETABEK, MAX_ROOMS, TEST_SLUGS

KEY = ["district", "land_area", "building_area", "bedrooms", "bathrooms"]
TABLE = ROOT / "reports" / "tables" / "noise_floor.csv"


def pair_gaps(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, group in df.groupby(KEY):
        for a, b in itertools.combinations(group.price, 2):
            rows.append({"gap": abs(np.log(a / b))})
    return pd.DataFrame(rows)


def noise_table() -> pd.DataFrame:
    df = pd.read_csv(INTERIM / "portal_listings.csv")
    df = df[df.city.str.contains(JABODETABEK) & (df.status == "active") & df.on_market & (df.bedrooms <= MAX_ROOMS) & (df.bathrooms <= MAX_ROOMS)]
    df = df[~df.slug.isin(TEST_SLUGS.read_text(encoding="utf-8").split())]
    df = df[df.groupby(KEY).price.transform("size") >= 2]
    gaps = pair_gaps(df)
    different = gaps[gaps.gap > 0].gap
    # two independent noisy asking prices of one house differ by sqrt(2) times the single-listing spread (normal approximation)
    return pd.DataFrame([{"pairs": len(gaps), "groups": df.groupby(KEY).ngroups, "share with equal price": (gaps.gap == 0).mean(),
                          "median gap, all pairs": gaps.gap.median(), "median gap, unequal prices": different.median(),
                          "implied median error, all pairs": gaps.gap.median() / np.sqrt(2),
                          "implied median error, unequal prices": different.median() / np.sqrt(2)}])


if __name__ == "__main__":
    table = noise_table()
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    table.round(3).to_csv(TABLE, index=False)
    print(table.round(3).T.to_string(header=False))
