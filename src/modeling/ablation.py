"""E7: drop one feature group at a time from the chosen model and compare with the full model on identical folds."""

import pandas as pd

from src.modeling.dataset import load_usable
from src.modeling.experiments import log_result, run_cv
from src.modeling.final import E4_FEATURES, FEATURE_GROUPS, fit_predict

if __name__ == "__main__":
    df = load_usable()
    full = {}
    for scheme in ("random", "spatial"):
        metrics, _, full[scheme] = run_cv(df, lambda tr, te: fit_predict(tr, te, E4_FEATURES), scheme)
        log_result("E7 xgb tuned, all features", scheme, len(df), metrics)
        print(f"all features      {scheme:8s} median APE {metrics['median_ape']:.1%}", flush=True)
    rows = []
    for group, columns in FEATURE_GROUPS.items():
        kept = [f for f in E4_FEATURES if f not in columns]
        row = {"dropped group": group, "features left": len(kept)}
        for scheme in ("random", "spatial"):
            metrics, _, per_repeat = run_cv(df, lambda tr, te, k=kept: fit_predict(tr, te, k), scheme)
            log_result(f"E7 without {group}", scheme, len(df), metrics)
            diff = (per_repeat - full[scheme]) * 100
            row[f"{scheme} median APE"] = round(metrics["median_ape"] * 100, 1)
            row[f"{scheme} change (points)"] = round(diff.mean(), 2)
            row[f"{scheme} repeats better without"] = int((diff < 0).sum())
        rows.append(row)
        print(f"without {group:18s} done", flush=True)
    table = pd.DataFrame(rows).sort_values("spatial change (points)")
    print(table.to_string(index=False))
