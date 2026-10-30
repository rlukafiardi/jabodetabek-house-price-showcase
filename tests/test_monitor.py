import numpy as np
import pandas as pd

from src.pipeline.monitor import PSI_ALERT, drift_table, performance, psi


def test_psi_of_the_same_distribution_is_near_zero():
    rng = np.random.default_rng(0)
    assert psi(pd.Series(rng.normal(size=5000)), pd.Series(rng.normal(size=5000))) < 0.05


def test_psi_flags_a_shifted_distribution():
    rng = np.random.default_rng(0)
    assert psi(pd.Series(rng.normal(size=5000)), pd.Series(rng.normal(1.0, 1, size=5000))) > PSI_ALERT


def test_psi_sees_a_jump_in_missing_values():
    rng = np.random.default_rng(0)
    reference = pd.Series(rng.normal(size=5000))
    current = reference.sample(2000, random_state=1).reset_index(drop=True)
    current[:1000] = np.nan
    assert psi(reference, current) > PSI_ALERT


def test_drift_table_skips_constant_features_and_sorts_by_psi():
    rng = np.random.default_rng(0)
    ref = pd.DataFrame({"a": rng.normal(size=2000), "b": rng.normal(size=2000), "const": 1.0})
    now = pd.DataFrame({"a": rng.normal(2.0, 1, size=2000), "b": rng.normal(size=2000), "const": 1.0})
    table = drift_table(ref, now, ["a", "b", "const"])
    assert list(table.feature) == ["a", "b"]


def test_performance_batch_summary():
    result = performance(pd.Series([0.1, 0.2, 0.3]), pd.Series([-0.1, 0.0, 0.1]))
    assert result == {"n": 3, "median_ape": 0.2, "bias": 0.0}
