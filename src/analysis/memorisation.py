"""Does a model file leak training listings? For each ensemble member, the median error on the rows it was fitted on versus on
rows it never saw (5-fold random CV, training part only). A model whose in-sample error is far below its held-out error stores
individual listings (extra trees with leaves of one listing do), so it should not be shipped to browsers as it is.
Writes reports/tables/memorisation.csv."""

import numpy as np
import pandas as pd

from src.config import ROOT
from src.modeling.compare_targets import split_folds
from src.modeling.dataset import load_usable
from src.modeling.ensemble import FEATURES, add_words, fit_parts, target, text_scores

TABLE = ROOT / "reports" / "tables" / "memorisation.csv"


def ape(pred: np.ndarray, df: pd.DataFrame) -> np.ndarray:
    return np.abs(np.exp(pred) * df.land_area.to_numpy() / df.price.to_numpy() - 1)


if __name__ == "__main__":
    df = add_words(load_usable())
    columns = FEATURES + ["text_score"]
    rows = []
    for train_idx, test_idx in split_folds(df, "random", 0):
        train, test = df.iloc[train_idx], df.iloc[test_idx]
        train_score, test_score = text_scores(train, test)
        train, test = train.assign(text_score=train_score), test.assign(text_score=test_score)
        parts = fit_parts(train[columns], target(train))
        predictions = {name: (m.predict(train[columns]), m.predict(test[columns])) for name, m in parts.items()}
        predictions["ensemble"] = tuple(np.mean([p[i] for p in predictions.values()], axis=0) for i in (0, 1))
        for name, (fitted, held_out) in predictions.items():
            rows.append({"model": name, "in-sample median error": np.median(ape(fitted, train)), "held-out median error": np.median(ape(held_out, test)),
                         "in-sample within 5%": (ape(fitted, train) <= 0.05).mean(), "held-out within 5%": (ape(held_out, test) <= 0.05).mean()})
    table = pd.DataFrame(rows).groupby("model", sort=False).mean()
    table["held-out / in-sample"] = table["held-out median error"] / table["in-sample median error"]
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    table.round(3).to_csv(TABLE)
    print((table * 100).round(1).drop(columns="held-out / in-sample").join(table["held-out / in-sample"].round(1)).to_string())
