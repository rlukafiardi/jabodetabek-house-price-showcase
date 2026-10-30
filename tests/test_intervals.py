import numpy as np
import pandas as pd

from src.modeling.intervals import LARGE_PLOT_M2, LARGE_PLOTS, REPEATS, apply_range, range_table


def errors() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    n = 600 * REPEATS  # enough large plots to pass the minimum per band
    land = np.where(np.arange(n) % 4 == 0, LARGE_PLOT_M2 + 100, 100)
    spread = np.where(land > LARGE_PLOT_M2, 0.6, 0.2)  # large plots are harder
    return pd.DataFrame({"city": np.where(np.arange(n) % 2 == 0, "Kota A", "Kota B"), "land_area": land, "log_ratio": rng.normal(0, 1, n) * spread})


def test_ranges_are_ordered_and_contain_the_estimate():
    table = range_table(errors())
    assert (table.low < table.low_50).all() and (table.low_50 < 1).all() and (1 < table.high_50).all() and (table.high_50 < table.high).all()


def test_large_plot_range_is_wider_than_the_overall_one():
    table = range_table(errors())
    assert LARGE_PLOTS in table.index
    assert table.loc[LARGE_PLOTS, "high"] > table.loc["all cities", "high"]


def test_apply_range_scales_the_estimate_and_falls_back_to_all_cities():
    table = range_table(errors())
    low, high = apply_range(np.array([1000.0, 1000.0]), pd.Series(["Kota A", "Unknown"]), table)
    assert low[0] == 1000 * table.loc["Kota A", "low"] and high[1] == 1000 * table.loc["all cities", "high"]


def test_apply_range_uses_the_large_plot_band_only_above_the_threshold():
    table = range_table(errors())
    land = pd.Series([LARGE_PLOT_M2 + 1, LARGE_PLOT_M2])
    low, high = apply_range(np.array([1000.0, 1000.0]), pd.Series(["Kota A", "Kota A"]), table, land_area=land)
    assert high[0] == 1000 * table.loc[LARGE_PLOTS, "high"] and high[1] == 1000 * table.loc["Kota A", "high"]
