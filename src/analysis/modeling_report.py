"""Modeling report (reports/modeling.html, PNGs, CSV tables): final test results, feature importance (XGBoost gain,
TreeSHAP, linear-regression coefficients) and the experiment history. Uses the results already logged; the test-set
predictions are the same deterministic refit as src/modeling/evaluate.py, not a new evaluation. The final model is an ensemble
of three regressors; SHAP and gain describe its XGBoost member (the strongest one), the coefficients a separate linear model."""

import html

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import xgboost as xgb
from plotly.subplots import make_subplots
from scipy.stats import spearmanr
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.analysis.eda import LABELS
from src.analysis.html_report import BLUE, BLUES, GREY, MUTED, RED, page, plots_html, save_pngs, section, styled, table_html, tile
from src.config import ROOT
from src.modeling.dataset import load_usable
from src.modeling.ensemble import MODEL_FEATURES, add_words, fit_parts, text_scores
from src.modeling.ensemble import fit_predict as ensemble_predict
from src.modeling.final import E4_FEATURES

REPORT = ROOT / "reports" / "modeling.html"
FIGURES = ROOT / "reports" / "figures"
TABLES = ROOT / "reports" / "tables"
FINAL_NAME = "ensemble + spec + context + text score (final)"
TOP_SHAP = 12


def label(feature: str) -> str:
    extra = {"floors_missing": "floors missing (flag)", "coord_is_centroid": "coordinate is a district centroid",
             "text_score": "text score (title and description)", "spec_garage": "garage (spec)", "spec_maid_rooms": "maid rooms (spec)",
             "spec_water_pam": "piped water PAM (spec)"}
    if feature.startswith("txt_"):
        return "text: " + feature.removeprefix("txt_").replace("_", " ")
    return LABELS.get(feature) or extra.get(feature, feature)


def target(df: pd.DataFrame) -> pd.Series:
    return np.log(df.price / df.land_area)


def pct(log_effect):
    """A change in log price per m² as a percentage change in price per m²."""
    return (np.exp(log_effect) - 1) * 100


def test_results(results: pd.DataFrame, n_test: int) -> go.Figure:
    r = results.iloc[::-1]
    fig = go.Figure(go.Bar(
        x=r.median_ape * 100, y=r.index, orientation="h", marker_color=[BLUE if m == FINAL_NAME else GREY for m in r.index],
        error_x=dict(type="data", symmetric=False, array=(r.median_ci_high - r.median_ape) * 100,
                     arrayminus=(r.median_ape - r.median_ci_low) * 100, color=MUTED, thickness=1.5),
        customdata=np.c_[r.median_ci_low * 100, r.median_ci_high * 100, r.within_20pct * 100],
        hovertemplate="%{y}<br>median error %{x:.1f}% (95%: %{customdata[0]:.1f}-%{customdata[1]:.1f})<br>%{customdata[2]:.0f}% within ±20%<extra></extra>"))
    fig.update_xaxes(title=f"median absolute % error of the price on the {n_test} test listings (bars: 95% bootstrap interval)")
    return styled(fig, "Final model against the alternatives, on listings never used for training", height=340)


def predicted_vs_actual(test: pd.DataFrame, pred_ppm2: np.ndarray) -> go.Figure:
    actual = test.price / test.land_area / 1e6
    predicted = pred_ppm2 / 1e6
    lo, hi = min(actual.min(), predicted.min()) * 0.8, max(actual.max(), predicted.max()) * 1.2
    line = np.array([lo, hi])
    fig = go.Figure([
        go.Scatter(x=line, y=line * 1.2, mode="lines", line=dict(color=GREY, dash="dash", width=1), hoverinfo="skip", name="±20%"),
        go.Scatter(x=line, y=line * 0.8, mode="lines", line=dict(color=GREY, dash="dash", width=1), hoverinfo="skip", showlegend=False),
        go.Scatter(x=line, y=line, mode="lines", line=dict(color=MUTED, width=1), hoverinfo="skip", name="perfect"),
        go.Scatter(x=actual, y=predicted, mode="markers", marker=dict(color=BLUE, size=7, opacity=0.7), name="test listing",
                   customdata=test.city, hovertemplate="%{customdata}<br>actual %{x:.1f}, predicted %{y:.1f} M IDR/m²<extra></extra>"),
    ])
    ticks = [2, 5, 10, 20, 50, 100]
    fig.update_xaxes(type="log", title="actual asking price per m² of land (M IDR)", tickvals=ticks, ticktext=[str(t) for t in ticks])
    fig.update_yaxes(type="log", title="predicted (M IDR)", tickvals=ticks, ticktext=[str(t) for t in ticks])
    return styled(fig, "Predicted vs actual price per m² (test set)", height=560, legend=True)


def bias_by_quartile(test: pd.DataFrame, pred_ppm2: np.ndarray) -> tuple[go.Figure, pd.Series]:
    actual = test.price / test.land_area
    signed = (pred_ppm2 - actual) / actual * 100
    quartile = pd.qcut(actual, 4, labels=["cheapest 25%", "2nd quarter", "3rd quarter", "dearest 25%"])
    bias = signed.groupby(quartile, observed=True).median()
    fig = go.Figure(go.Bar(x=bias.index.astype(str), y=bias.values, marker_color=[RED if v < 0 else BLUE for v in bias],
                           text=[f"{v:+.0f}%" for v in bias], textposition="outside", hovertemplate="%{x}: median error %{y:+.1f}%<extra></extra>"))
    fig.add_hline(y=0, line_color=MUTED, line_width=1)
    fig.update_yaxes(title="median error (%)")
    return styled(fig, "The model pulls extremes toward the middle (test set; + means predicted too high)", height=340), bias


def errors_by_city(segments: pd.DataFrame) -> go.Figure:
    city = segments[segments.segment == "city"].sort_values("median_ape")
    fig = go.Figure(go.Bar(x=city.median_ape * 100, y=[f"{c} (n={n})" for c, n in zip(city.index, city.n)], orientation="h",
                           marker_color=BLUE, hovertemplate="%{y}: median error %{x:.1f}%<extra></extra>"))
    fig.update_xaxes(title="median absolute % error on test listings (small n: read with care)")
    return styled(fig, "Test error by city", height=460)


def shap_values(model, x: pd.DataFrame) -> pd.DataFrame:
    """Exact TreeSHAP from XGBoost itself: one contribution per feature and listing, in log price per m² (bias column dropped)."""
    contributions = model.get_booster().predict(xgb.DMatrix(x), pred_contribs=True)
    return pd.DataFrame(contributions[:, :-1], columns=x.columns, index=x.index)


def shap_ranking(shap: pd.DataFrame) -> tuple[go.Figure, pd.Series]:
    mean_abs = shap.abs().mean().sort_values()
    fig = go.Figure(go.Bar(x=pct(mean_abs.values), y=[label(f) for f in mean_abs.index], orientation="h", marker_color=BLUE,
                           hovertemplate="%{y}: moves price per m² by %{x:.1f}% on average<extra></extra>"))
    fig.update_xaxes(title="mean absolute SHAP effect on price per m² (%)")
    return styled(fig, "SHAP: how much each feature moves the prediction, on average", height=760), mean_abs.sort_values(ascending=False)


def shap_beeswarm(shap: pd.DataFrame, x: pd.DataFrame, top: list[str]) -> go.Figure:
    rng = np.random.default_rng(0)
    fig = go.Figure()
    for i, feature in enumerate(reversed(top)):
        value = x[feature]
        rank = value.rank(pct=True).fillna(0.5)
        fig.add_trace(go.Scatter(
            x=pct(shap[feature]), y=i + rng.uniform(-0.3, 0.3, len(value)), mode="markers",
            marker=dict(size=4, color=rank, coloraxis="coloraxis", opacity=0.8),
            customdata=value, hovertemplate=f"{html.escape(label(feature))}: %{{customdata}}<br>effect %{{x:+.1f}}%<extra></extra>"))
    fig.update_layout(coloraxis=dict(colorscale=BLUES, cmin=0, cmax=1, colorbar=dict(title="feature value", thickness=12, tickvals=[0, 1], ticktext=["low", "high"])))
    fig.add_vline(x=0, line_color=MUTED, line_width=1)
    fig.update_yaxes(tickvals=list(range(len(top))), ticktext=[label(f) for f in reversed(top)])
    fig.update_xaxes(title="SHAP effect on this listing's price per m² (%)")
    return styled(fig, "SHAP per listing: direction and spread of each top feature's effect", height=620)


def shap_dependence(shap: pd.DataFrame, x: pd.DataFrame, features: list[str]) -> go.Figure:
    fig = make_subplots(rows=2, cols=2, subplot_titles=[label(f) for f in features], horizontal_spacing=0.1, vertical_spacing=0.18)
    for k, feature in enumerate(features):
        fig.add_trace(go.Scatter(x=x[feature], y=pct(shap[feature]), mode="markers", marker=dict(color=BLUE, size=5, opacity=0.5),
                                 hovertemplate="value %{x}<br>effect %{y:+.1f}%<extra></extra>"), row=k // 2 + 1, col=k % 2 + 1)
    fig.update_yaxes(title="effect (%)")
    return styled(fig, "SHAP dependence: effect on price per m² (%) as the feature value changes", height=640)


def gain_ranking(model, features: list[str]) -> tuple[go.Figure, pd.Series]:
    gain = pd.Series(model.get_booster().get_score(importance_type="gain"))
    share = (gain / gain.sum() * 100).reindex(features).fillna(0).sort_values()
    fig = go.Figure(go.Bar(x=share.values, y=[label(f) for f in share.index], orientation="h", marker_color=BLUE,
                           hovertemplate="%{y}: %{x:.1f}% of the total gain<extra></extra>"))
    fig.update_xaxes(title="share of XGBoost's total split gain (%)")
    return styled(fig, "XGBoost built-in importance (gain)", height=760), share.sort_values(ascending=False)


def vif(x: pd.DataFrame) -> pd.Series:
    return pd.Series({c: 1 / (1 - LinearRegression().fit(x.drop(columns=c), x[c]).score(x.drop(columns=c), x[c])) for c in x})


def linear_coefficients(train: pd.DataFrame, features: list[str]) -> tuple[go.Figure, pd.DataFrame]:
    """Linear regression on standardised features: % change in price per m² for a one-standard-deviation increase."""
    model = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LinearRegression()).fit(train[features], target(train))
    filled = pd.DataFrame(model[:2].transform(train[features]), columns=features)
    table = pd.DataFrame({"feature": [label(f) for f in features], "effect_pct_per_sd": pct(model[-1].coef_), "vif": vif(filled).to_numpy()})
    table = table.reindex(table.effect_pct_per_sd.abs().sort_values().index)
    colours = [GREY if v >= 10 else (RED if e < 0 else BLUE) for e, v in zip(table.effect_pct_per_sd, table.vif)]
    fig = go.Figure(go.Bar(x=table.effect_pct_per_sd, y=[f"{f} (VIF {v:.0f})" if v >= 10 else f for f, v in zip(table.feature, table.vif)],
                           orientation="h", marker_color=colours, hovertemplate="%{y}: %{x:+.1f}% per standard deviation<extra></extra>"))
    fig.update_xaxes(title="% change in price per m² for +1 standard deviation (grey: VIF 10 or more, not readable on its own)")
    return styled(fig, "Explanatory linear model: direction and size of each feature's effect", height=760), table.iloc[::-1]


def segment_figure(segments: pd.DataFrame) -> go.Figure:
    shown = segments[segments.group != "city"].copy()
    shown["name"] = shown.group + ": " + shown.segment.astype(str)
    shown = shown.sort_values("median_ape")
    fig = go.Figure(go.Bar(x=shown.median_ape * 100, y=shown.name, orientation="h", customdata=np.c_[shown.n, shown.bias * 100],
                           marker_color=[RED if abs(b) > 0.10 else BLUE for b in shown.bias],
                           hovertemplate="%{y}<br>median error %{x:.1f}% on %{customdata[0]} listings, bias %{customdata[1]:+.1f}%<extra></extra>"))
    fig.update_xaxes(title="median absolute % error, out-of-fold on the training part (red: bias beyond ±10%)")
    return styled(fig, "Where the error sits", height=640)


def backtest_figure(backtest: pd.DataFrame) -> go.Figure:
    fig = go.Figure([go.Bar(x=part.target_month, y=part.median_ape * 100, name=label, marker_color=colour, customdata=part.train_rows,
                            hovertemplate="%{x}: %{y:.1f}% (trained on %{customdata} listings)<extra>" + label + "</extra>")
                     for label, colour, part in (("trained on the past only", BLUE, backtest[backtest.train == "past"]),
                                                 ("trained on mixed months, same size", GREY, backtest[backtest.train == "mixed"]))])
    fig.update_layout(barmode="group")
    fig.update_xaxes(type="category")  # month labels, not dates
    fig.update_yaxes(title="median absolute % error of the price", rangemode="tozero")
    return styled(fig, "Does the model go stale? Each month scored by a past-only and a mixed-period model", height=380, legend=True)


def price_level_figure(train: pd.DataFrame) -> go.Figure:
    month = train.created_at.dt.tz_localize(None).dt.to_period("M")
    level = (train.price / train.land_area / 1e6).groupby(month).agg(["median", "size"])
    fig = go.Figure(go.Scatter(x=level.index.astype(str), y=level["median"], mode="lines+markers", line=dict(color=BLUE, width=2),
                               customdata=level["size"], hovertemplate="%{x}: %{y:.1f} M IDR/m² on %{customdata} listings<extra></extra>"))
    fig.update_xaxes(type="category")
    fig.update_yaxes(title="median asking price per m² of land (M IDR)", rangemode="tozero")
    return styled(fig, "Price level by listing month (mid-2025 months hold few surviving listings)", height=340)


def dot_rows(rows: pd.DataFrame, title: str, height: int) -> go.Figure:
    rows = rows.sort_values("spatial", ascending=False)
    fig = go.Figure([
        go.Scatter(x=rows.random, y=rows.index, mode="markers", name="random CV", marker=dict(color=BLUE, size=10),
                   hovertemplate="%{y}: %{x:.1f}%<extra>random CV</extra>"),
        go.Scatter(x=rows.spatial, y=rows.index, mode="markers", name="spatial-block CV", marker=dict(color=MUTED, size=10, symbol="diamond"),
                   hovertemplate="%{y}: %{x:.1f}%<extra>spatial-block CV</extra>"),
    ])
    fig.update_xaxes(title="median absolute % error, cross-validation on the training part")
    return styled(fig, title, height=height, legend=True)


def ablation_bars(exp: pd.DataFrame) -> go.Figure:
    full = exp.loc["E7 xgb tuned, all features"]
    rows = exp[exp.index.str.startswith("E7 without")]
    change = (rows - full).sort_values("spatial")
    names = change.index.str.removeprefix("E7 without ")
    fig = go.Figure([
        go.Bar(x=change.random, y=names, orientation="h", name="random CV", marker_color=BLUE, hovertemplate="%{y}: %{x:+.2f} points<extra>random CV</extra>"),
        go.Bar(x=change.spatial, y=names, orientation="h", name="spatial-block CV", marker_color=GREY, hovertemplate="%{y}: %{x:+.2f} points<extra>spatial CV</extra>"),
    ])
    fig.update_layout(barmode="group")
    fig.update_xaxes(title="change in median % error when the group is removed (+ means the group was helping)")
    return styled(fig, "Ablation: what happens when each feature group is removed", height=520, legend=True)


if __name__ == "__main__":
    train, test = add_words(load_usable("train")), add_words(load_usable("test"))
    pred_ppm2 = np.exp(ensemble_predict(train, test))  # the model predicts log price per m² of land
    inner_scores, _ = text_scores(train, test.iloc[:1])  # out-of-fold text score of the training rows
    train_x = train[MODEL_FEATURES].assign(text_score=inner_scores)
    model = fit_parts(train_x, target(train), members=("xgboost", "ridge"))["xgboost"]  # the member that SHAP and gain describe
    results = pd.read_csv(TABLES / "final_test.csv", index_col="model")
    segments = pd.read_csv(TABLES / "final_test_segments.csv", index_col=0)
    log = pd.read_csv(TABLES / "experiments.csv")
    exp = log.pivot_table(index="experiment", columns="cv", values="median_ape")  # one row per experiment; n differs (see the log)

    # constant features (e.g. the take-over flag, whose listings are out of scope) cannot be split on or explained
    model_columns = list(train_x.columns)
    features = [f for f in model_columns if train_x[f].nunique() > 1]
    shap = shap_values(model, train_x)[features]
    figures = {}
    figures["test"] = test_results(results, len(test))
    figures["pred_actual"] = predicted_vs_actual(test, pred_ppm2)
    figures["bias"], bias = bias_by_quartile(test, pred_ppm2)
    figures["city"] = errors_by_city(segments)
    figures["shap_rank"], shap_rank = shap_ranking(shap)
    top = list(shap_rank.index[:TOP_SHAP])
    figures["shap_swarm"] = shap_beeswarm(shap, train_x, top)
    figures["shap_dependence"] = shap_dependence(shap, train_x, [f for f in top if train_x[f].nunique() > 2][:4])
    figures["gain"], gain = gain_ranking(model, features)
    figures["linear"], coefficients = linear_coefficients(train, [f for f in E4_FEATURES if train[f].nunique() > 1])
    figures["screen"] = dot_rows(exp[exp.index.str.startswith("D ")].rename(index=lambda n: n.removeprefix("D ")),
                                 "Model screen: 17 families with default settings", height=620)
    figures["tuned"] = dot_rows(exp[exp.index.str.startswith("E6 tuned")].rename(index=lambda n: n.removeprefix("E6 tuned ")),
                                "After tuning: best configuration per family", height=360)
    figures["ablation"] = ablation_bars(exp)
    ladder = ["E8 final model", "E9a + spec fields", "E12 ensemble xgb + extra trees + ridge", "E13 + text score on xgboost",
              "E14a ensemble + spec fields + text score", "E18 ensemble + neighbourhood context"]
    rejected = ["E15 ensemble + comparables k=10", "E16a ensemble + size ratio", "E20 ensemble + wealth index and population",
                "E21 ensemble + context + size ratio", "E22 ensemble + text score, no spec fields", "E19a ensemble without extra trees (shippable)"]
    figures["features"] = dot_rows(exp.loc[[n for n in ladder if n in exp.index]], "Steps that made the final model (training part, paired CV)", height=360)
    figures["rejected"] = dot_rows(exp.loc[[n for n in rejected if n in exp.index]], "Ideas tried and not adopted", height=360)
    segment_table = pd.read_csv(TABLES / "error_analysis.csv")
    tail = pd.read_csv(TABLES / "error_analysis_tail.csv").iloc[0]
    backtest = pd.read_csv(TABLES / "temporal_backtest.csv")
    drift = pd.read_csv(TABLES / "drift_early_vs_late.csv")
    figures["segments"] = segment_figure(segment_table)
    figures["backtest"] = backtest_figure(backtest)
    figures["price_level"] = price_level_figure(train)
    save_pngs(figures, FIGURES, "model")
    shap_table = pd.DataFrame({"feature": [label(f) for f in shap_rank.index], "mean_abs_effect_pct": pct(shap_rank.to_numpy())})
    for name, table in {"model_shap_importance": shap_table, "model_gain_importance": gain.rename("gain_share_pct").rename(index=label).reset_index(),
                        "model_linear_coefficients": coefficients}.items():
        table.round(3).to_csv(TABLES / f"{name}.csv", index=False)

    plot = plots_html(figures)
    final = results.loc[FINAL_NAME]
    best_baseline = results.loc[[m for m in results.index if m.startswith("B")]].median_ape.min()
    spatial_cv = exp.loc["E18 ensemble + neighbourhood context", "spatial"]
    city_n = segments[segments.segment == "city"].n
    rank_agreement = spearmanr(shap_rank.reindex(features), gain.reindex(features))[0]
    top3 = ", ".join(label(f) for f in shap_rank.index[:3])
    readable = coefficients[coefficients.vif < 10]
    strongest = readable.iloc[readable.effect_pct_per_sd.abs().argmax()]
    limits = "".join(f"<li>{html.escape(t)}</li>" for t in [
        "Asking prices, not transaction prices: a level bias against deal prices is likely.",
        "One portal (Portal) and a slug-keyword sampler: listings whose slug names no place are under-represented.",
        "About a quarter of the listings carry a district-centroid coordinate, so their location features are approximate.",
        "Thin coverage in remote kecamatan (Kab. Bogor, Kab. Tangerang, Kab. Bekasi): errors there are the largest.",
        f"Test counts per city are small ({city_n.min()} to {city_n.max()}), so per-city errors are indicative only.",
        "The test set is now spent: further model changes need new data and a fresh holdout.",
    ])
    sections = [
        section("Final result", f"Median error {final.median_ape:.1%} (95% interval {final.median_ci_low:.1%}-{final.median_ci_high:.1%}) against "
                f"{best_baseline:.1%} for the best baseline; {final.within_20pct:.0%} of test listings priced within ±20%.",
                plot["test"] + table_html((results * 100).round(1).reset_index())),
        section("Predicted vs actual", f"Points close to the line are well priced; the dashed band is ±20%. Cheapest quarter predicted "
                f"{bias.iloc[0]:+.0f}%, dearest quarter {bias.iloc[-1]:+.0f}%: the model pulls extremes toward the middle.",
                plot["pred_actual"] + plot["bias"]),
        section("Errors by city", "Small test counts per city: differences of a few points are noise.", plot["city"]),
        section("Error analysis", f"Out-of-fold on the training part: median {tail.median_ape:.1%}, mean {tail.mean_ape:.1%}; {tail.within_10pct:.0%} of listings within 10%, "
                f"{tail.within_20pct:.0%} within 20%, {tail.over_50pct:.0%} more than 50% off. The worst 10% of listings carry {tail.worst_10pct_share_of_error:.0%} of the "
                "absolute error. The cheapest quarter is over-predicted and the dearest under-predicted, plots over 300 m² are the hardest, and listings with "
                "missing floors or short descriptions are a few points worse.", plot["segments"] + table_html(segment_table.assign(median_ape=segment_table.median_ape * 100, bias=segment_table.bias * 100).round(1))),
        section("Stability over time", "A model trained on the past scores later months as well as one trained on mixed months of the same size, so it does not go "
                "stale within one to four months and a monthly refresh is enough. The largest input drift between the early and the late months is "
                f"PSI {drift.psi.max():.2f} ({drift.feature.iloc[0]}), below the 0.2 alert level.",
                plot["backtest"] + plot["price_level"] + table_html(drift.head(8).round(3))),
        section("Feature importance: SHAP", f"Exact TreeSHAP from XGBoost, on the {len(train):,} training listings. Strongest: {top3}. "
                "Each dot in the swarm is a listing: right means the feature raised its predicted price.",
                plot["shap_rank"] + plot["shap_swarm"] + plot["shap_dependence"]),
        section("Feature importance: XGBoost gain", f"The model's own split-gain ranking agrees with SHAP at rank correlation {rank_agreement:.2f}; "
                "gain favours features used in many splits, SHAP measures effect on the prediction, so SHAP is the one to quote.", plot["gain"]),
        section("Explanatory linear model", f"Linear regression on standardised features ({results.loc['linear regression (explanatory)', 'median_ape']:.1%} "
                f"median error on test). Largest readable effect: {strongest.feature}, {strongest.effect_pct_per_sd:+.0f}% per standard deviation. "
                "Grey bars have a VIF of 10 or more and cannot be read on their own.",
                plot["linear"] + table_html(coefficients.round(1))),
        section("How we got here", f"Baselines, a 17-family screen, tuning and ablation (run early, on 1,000 to 2,700 training rows), then the steps that built the ensemble, "
                f"all on the training part with paired CV. Final model: ensemble on {len(model_columns)} inputs, {spatial_cv:.1f}% median error under spatial-block CV.",
                plot["features"] + plot["rejected"] + plot["screen"] + plot["tuned"] + plot["ablation"]),
        section("Limitations", "What these numbers do and do not say.", f"<ul>{limits}</ul>"),
    ]
    tiles = [
        tile(f"{final.median_ape:.1%}", "median % error on the test set"),
        tile(f"{final.within_20pct:.0%}", "test listings within ±20%"),
        tile(f"{best_baseline:.1%}", "best simple baseline"),
        tile(f"{spatial_cv:.1f}%", "error on unseen areas (spatial CV)"),
        tile(f"{len(model_columns)}", "model inputs (incl. text score)"),
    ]
    subtitle = (f"Mean of XGBoost, extra trees and ridge predicting log asking price per m² of land; trained on {len(train):,} listings, tested once on {len(test)}. "
                "Generated by <code>uv run python -m src.analysis.modeling_report</code>.")
    REPORT.write_text(page("Jabodetabek house prices: modeling", subtitle, tiles, sections), encoding="utf-8")
    print(f"wrote {REPORT} ({REPORT.stat().st_size / 1e6:.1f} MB), {len(figures)} PNGs")
    print("SHAP top 10 (% effect):", {label(f): round(pct(v), 1) for f, v in shap_rank.head(10).items()})
    print("gain top 5 (%):", {label(f): round(v, 1) for f, v in gain.head(5).items()}, "| SHAP-gain rank correlation:", round(rank_agreement, 2))
    print(coefficients.round(1).head(10).to_string(index=False))
