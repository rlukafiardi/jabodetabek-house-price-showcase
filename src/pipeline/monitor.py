"""Drift checks for the live model (see ds-workflow phase 7): input drift (PSI and KS against the training distribution) and
performance drift (rolling error and bias on newly listed houses, whose asking price is known at once)."""

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp

PSI_ALERT = 0.2  # common rule of thumb: below 0.1 stable, above 0.2 a clear shift
BINS = 10


def psi(reference: pd.Series, current: pd.Series) -> float:
    """Population stability index with bins at the reference deciles (a missing value is its own bin)."""
    edges = np.unique(np.nanquantile(reference, np.linspace(0, 1, BINS + 1)))
    edges[0], edges[-1] = -np.inf, np.inf
    def shares(values: pd.Series) -> np.ndarray:
        counts = np.append(np.histogram(values.dropna(), edges)[0], values.isna().sum())
        return np.clip(counts / max(len(values), 1), 1e-4, None)
    expected, actual = shares(reference), shares(current)
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def drift_table(reference: pd.DataFrame, current: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    """PSI and the KS statistic of each numeric feature, largest PSI first."""
    rows = [{"feature": f, "psi": psi(reference[f], current[f]), "ks": ks_2samp(reference[f].dropna(), current[f].dropna()).statistic,
             "missing_ref": reference[f].isna().mean(), "missing_now": current[f].isna().mean()}
            for f in features if reference[f].nunique() > 1]
    return pd.DataFrame(rows).sort_values("psi", ascending=False).reset_index(drop=True)


def performance(ape: pd.Series, signed: pd.Series) -> dict[str, float]:
    """Median error and median signed error (bias) of a batch of newly listed houses."""
    return {"n": len(ape), "median_ape": float(ape.median()), "bias": float(signed.median())}
