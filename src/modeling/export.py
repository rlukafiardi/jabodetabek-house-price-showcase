"""Export the shippable model (XGBoost + ridge on the final features plus a text score) to JSON for the browser, with parity
cases for the JavaScript predictor (app/model.js, app/test_parity.mjs). Extra trees are not exported: with single-listing leaves
they reproduce every training listing (src/analysis/memorisation.py). Training part only; cases come from training rows.
Writes app/model.json and app/parity.json (both gitignored build artefacts)."""

import json

import numpy as np
import pandas as pd

from src.config import ROOT
from src.modeling.dataset import load_usable
from src.modeling.ensemble import FEATURES, add_words, fit_parts, target, text_model, text_scores

APP = ROOT / "app"
PARITY_CASES = 300


def tree_arrays(tree: dict) -> dict:
    """One tree from XGBoost's JSON model (thresholds stored exactly as float32): split feature (-1 for a leaf), threshold or leaf
    value, yes (left) and no (right) child, and the child a missing value takes."""
    leaf = [left == -1 for left in tree["left_children"]]
    missing = [left if default_left else right for left, right, default_left in zip(tree["left_children"], tree["right_children"], tree["default_left"])]
    return {"feature": [-1 if is_leaf else f for is_leaf, f in zip(leaf, tree["split_indices"])], "value": tree["split_conditions"],
            "yes": tree["left_children"], "no": tree["right_children"], "missing": missing}


def nan_to_none(values) -> list:
    return [None if isinstance(v, float) and np.isnan(v) else v for v in values]


if __name__ == "__main__":
    train = add_words(load_usable("train"))
    columns = FEATURES + ["text_score"]
    y = target(train)
    inner_scores, _ = text_scores(train, train.iloc[:1])
    deployed_text = text_model().fit(train.words, y)
    parts = fit_parts(train[FEATURES].assign(text_score=inner_scores), y, members=("xgboost", "ridge"))

    learner = json.loads(parts["xgboost"].get_booster().save_raw("json"))["learner"]
    xgb = {"base_score": float(learner["learner_model_param"]["base_score"].strip("[]")),  # XGBoost 3 writes "[1.6E1]"
           "trees": [tree_arrays(tree) for tree in learner["gradient_booster"]["model"]["trees"]]}
    steps = parts["ridge"].named_steps
    ridge = {"medians": steps["simpleimputer"].statistics_.tolist(), "indicator_features": steps["simpleimputer"].indicator_.features_.tolist(),
             "mean": steps["standardscaler"].mean_.tolist(), "scale": steps["standardscaler"].scale_.tolist(),
             "coef": steps["ridgecv"].coef_.tolist(), "intercept": float(steps["ridgecv"].intercept_)}
    tfidf, text_ridge = deployed_text.named_steps["tfidfvectorizer"], deployed_text.named_steps["ridgecv"]
    text = {"vocabulary": {term: [int(i), float(tfidf.idf_[i])] for term, i in tfidf.vocabulary_.items()},
            "coef": text_ridge.coef_.tolist(), "intercept": float(text_ridge.intercept_)}
    APP.mkdir(exist_ok=True)
    (APP / "model.json").write_text(json.dumps({"features": columns, "xgboost": xgb, "ridge": ridge, "text": text}), encoding="utf-8")

    sample = train.sample(PARITY_CASES, random_state=0)
    x = sample[FEATURES].assign(text_score=deployed_text.predict(sample.words))
    xgb_pred, ridge_pred = parts["xgboost"].predict(x), parts["ridge"].predict(x)
    expected = np.mean([xgb_pred, ridge_pred], axis=0)
    cases = [{"features": dict(zip(FEATURES, nan_to_none(row[FEATURES].astype(float).tolist()))), "words": words, "expected": float(e),
              "parts": {"xgboost": float(a), "ridge": float(b), "text_score": float(s)}}
             for (_, row), words, e, a, b, s in zip(sample.iterrows(), sample.words, expected, xgb_pred, ridge_pred, x.text_score)]
    (APP / "parity.json").write_text(json.dumps(cases), encoding="utf-8")
    size = (APP / "model.json").stat().st_size / 1e6
    print(f"model.json {size:.1f} MB: {len(xgb['trees'])} trees, {len(text['vocabulary'])} text terms; {len(cases)} parity cases")
