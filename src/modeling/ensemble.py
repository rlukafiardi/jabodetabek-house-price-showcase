"""The chosen model (E18): mean of XGBoost, extra trees and ridge on the final features plus the agent-filled spec fields, the OSM
neighbourhood context and an out-of-fold TF-IDF text score, predicting log price per m² of land. Paired CV on identical folds:
20.3 / 23.1% median APE (random / spatial); E14a (the same without the context) was beaten in 5 of 5 repeats under both schemes,
and the single tuned XGBoost by about 1.7 / 1.3 points."""

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import RidgeCV
from sklearn.model_selection import KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from src.features.context import CONTEXT_FEATURES
from src.ingestion.parse import TEXT_FILE
from src.modeling.final import FINAL_FEATURES, SPEC_GROUP, XGB_PARAMS

FEATURES = FINAL_FEATURES + SPEC_GROUP
MODEL_FEATURES = FEATURES + CONTEXT_FEATURES


def target(df: pd.DataFrame) -> pd.Series:
    return np.log(df.price / df.land_area)


def add_words(df: pd.DataFrame) -> pd.DataFrame:
    """Cleaned title and description words (letters only, no emails or URLs) for the text model."""
    return df.assign(words=df.slug.map(pd.read_csv(TEXT_FILE).set_index("slug").words).fillna(""))


def text_model():
    return make_pipeline(TfidfVectorizer(min_df=5, max_df=0.5, ngram_range=(1, 2), sublinear_tf=True), RidgeCV(alphas=np.logspace(-1, 2, 8)))


def text_scores(train: pd.DataFrame, test: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Text-model prediction of the target: out-of-fold for training rows (an inner 5-fold split), from all of train for test rows."""
    y, inner = target(train), np.empty(len(train))
    for a, b in KFold(5, shuffle=True, random_state=0).split(train):
        inner[b] = text_model().fit(train.words.iloc[a], y.iloc[a]).predict(train.words.iloc[b])
    return inner, text_model().fit(train.words, y).predict(test.words)


MEMBERS = ("xgboost", "extra trees", "ridge")


def fit_parts(x: pd.DataFrame, y: pd.Series, xgb_params: dict = XGB_PARAMS, members: tuple[str, ...] = MEMBERS, extra_leaf: int = 1) -> dict:
    """The members of the ensemble, fitted: tuned XGBoost, extra trees (best E6 settings; leaves of extra_leaf listings) and ridge.
    With extra_leaf=1 the extra trees reproduce every training listing exactly (see src/analysis/memorisation.py)."""
    extra = make_pipeline(SimpleImputer(strategy="median"), ExtraTreesRegressor(n_estimators=300, max_features=0.33, min_samples_leaf=extra_leaf, random_state=0, n_jobs=-1))
    ridge = make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(), RidgeCV(alphas=np.logspace(-1, 3, 9)))
    models = {"xgboost": lambda: XGBRegressor(**xgb_params).fit(x, y), "extra trees": lambda: extra.fit(x, y), "ridge": lambda: ridge.fit(x, y)}
    return {name: models[name]() for name in members}


def ensemble(features: list[str], text: bool = False, xgb_params: dict = XGB_PARAMS,
             members: tuple[str, ...] = MEMBERS, extra_leaf: int = 1):
    """Mean of XGBoost, extra trees (best E6 settings) and ridge. text=True adds the out-of-fold text score as a feature."""
    def fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
        columns = list(features)
        if text:
            train_score, test_score = text_scores(train, test)
            train, test = train.assign(text_score=train_score), test.assign(text_score=test_score)
            columns += ["text_score"]
        parts = fit_parts(train[columns], target(train), xgb_params, members, extra_leaf)
        return np.mean([m.predict(test[columns]) for m in parts.values()], axis=0)
    return fit_predict


fit_predict = ensemble(MODEL_FEATURES, text=True)  # train and test need the words column (add_words)
