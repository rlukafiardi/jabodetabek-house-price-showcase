import pandas as pd
import pytest

from src.modeling import split
from src.modeling.split import carve_test


def test_carve_test_is_stratified_and_deterministic():
    df = pd.DataFrame({"slug": [f"s{i:03d}" for i in range(500)], "city": ["A"] * 300 + ["B"] * 150 + ["C"] * 50})
    test = carve_test(df)
    assert test == carve_test(df) == sorted(test)
    assert len(test) == 100
    share = df[df.slug.isin(test)].city.value_counts(normalize=True)
    assert abs(share["A"] - 0.6) < 0.03 and abs(share["C"] - 0.1) < 0.03


def test_fitted_listings_returns_exactly_the_listed_slugs(tmp_path, monkeypatch):
    # "b-old" is the same house as the later-crawled "a-new" (earlier slug): usable_listings would swap them, the fitted list must not
    listings = pd.DataFrame({"slug": ["a-new", "b-old", "c-other"], "price": [5, 5, 7], "created_at": pd.to_datetime(["2026-11-02"] * 3)})
    listings.to_csv(tmp_path / "portal_listings.csv", index=False)
    (tmp_path / "train_slugs.txt").write_text("b-old\nc-other\n", encoding="utf-8")
    monkeypatch.setattr(split, "INTERIM", tmp_path)
    monkeypatch.setattr(split, "FITTED_SLUGS", tmp_path / "train_slugs.txt")
    assert list(split.fitted_listings().slug) == ["b-old", "c-other"]
    (tmp_path / "train_slugs.txt").write_text("b-old\nmissing\n", encoding="utf-8")
    with pytest.raises(ValueError, match="1 of the 2 fitted slugs"):
        split.fitted_listings()
