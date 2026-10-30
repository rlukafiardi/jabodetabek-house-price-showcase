import pandas as pd

from src.modeling.split import carve_test


def test_carve_test_is_stratified_and_deterministic():
    df = pd.DataFrame({"slug": [f"s{i:03d}" for i in range(500)], "city": ["A"] * 300 + ["B"] * 150 + ["C"] * 50})
    test = carve_test(df)
    assert test == carve_test(df) == sorted(test)
    assert len(test) == 100
    share = df[df.slug.isin(test)].city.value_counts(normalize=True)
    assert abs(share["A"] - 0.6) < 0.03 and abs(share["C"] - 0.1) < 0.03
