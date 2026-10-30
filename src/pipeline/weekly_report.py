"""Weekly model-health report (reports/weekly_report.html): how the live model does on newly listed houses, whether the inputs
drifted, and which alerts fired. Thresholds come from the test score and the time-based backtest (see CLAUDE.md).
`build_report` takes the reference (training) rows, the new rows with their model estimates, and the parse rate of the crawl;
the weekly pipeline will call it with listings first seen after the live model's training cutoff. `--simulate` replays it on the
training part: a model trained up to SIMULATE_CUTOFF scores the listings created after it (created_at stands in for first_seen)."""

import sys

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from src.analysis.html_report import BLUE, GREY, MUTED, RED, page, plots_html, save_pngs, section, styled, table_html, tile
from src.config import ROOT
from src.modeling.dataset import load_usable
from src.modeling.ensemble import MODEL_FEATURES, add_words, fit_predict
from src.pipeline.monitor import PSI_ALERT, drift_table, psi

REPORT = ROOT / "reports" / "weekly_report.html"
ERROR_ALERT = 0.251  # top of the holdout interval for the median error (20.9 to 25.1%)
BIAS_ALERT, CITY_BIAS_ALERT = 0.05, 0.10
PARSE_MIN = 0.70
MIN_N, MIN_CITY_N = 200, 50  # cumulative error is only judged on this many new listings (monthly error swings about 3 points on 150-265)
SIMULATE_CUTOFF = "2026-07-01"
NOT_DRIFT_FEATURES = ["age_days"]  # measured from today, so it always drifts


def weekly_table(new: pd.DataFrame, date_col: str) -> pd.DataFrame:
    """Per week: new listings, median error of that week, cumulative median error and cumulative bias."""
    week = new[date_col].dt.tz_localize(None).dt.to_period("W").dt.start_time
    rows = []
    for start, part in new.groupby(week):
        so_far = new[week <= start]
        rows.append({"week": start, "n": len(part), "median_ape": part.ape.median(), "cum_n": len(so_far),
                     "cum_median_ape": so_far.ape.median(), "cum_bias": so_far.signed.median()})
    return pd.DataFrame(rows)


def alerts_for(weekly: pd.DataFrame, by_city: pd.DataFrame, drift: pd.DataFrame, parse_rate: float | None) -> list[str]:
    alerts = []
    last = weekly.iloc[-1]
    if last.cum_n >= MIN_N:
        if (weekly.tail(2).cum_median_ape > ERROR_ALERT).all() and len(weekly) >= 2:
            alerts.append(f"Median error {last.cum_median_ape:.1%} over {int(last.cum_n)} new listings, above {ERROR_ALERT:.1%} for two weeks in a row.")
        if abs(last.cum_bias) > BIAS_ALERT:
            alerts.append(f"Overall bias {last.cum_bias:+.1%} (limit ±{BIAS_ALERT:.0%}): estimates are {'too high' if last.cum_bias > 0 else 'too low'}.")
    alerts += [f"{city}: bias {row.bias:+.1%} on {int(row.n)} new listings (limit ±{CITY_BIAS_ALERT:.0%})."
               for city, row in by_city.iterrows() if row.n >= MIN_CITY_N and abs(row.bias) > CITY_BIAS_ALERT]
    alerts += [f"Input drift: {row.feature} PSI {row.psi:.2f} (limit {PSI_ALERT})." for row in drift.itertuples() if row.psi > PSI_ALERT]
    alerts += [f"Missing share of {row.feature} moved from {row.missing_ref:.0%} to {row.missing_now:.0%}." for row in drift.itertuples()
               if abs(row.missing_now - row.missing_ref) > 0.15]
    if parse_rate is not None and parse_rate < PARSE_MIN:
        alerts.append(f"Parse rate {parse_rate:.0%} is below {PARSE_MIN:.0%}: the page format may have changed.")
    return alerts


def error_figure(weekly: pd.DataFrame) -> go.Figure:
    fig = go.Figure([
        go.Bar(x=weekly.week, y=weekly.median_ape * 100, name="that week", marker_color=GREY, customdata=weekly.n,
               hovertemplate="week of %{x|%Y-%m-%d}: %{y:.1f}% on %{customdata} listings<extra></extra>"),
        go.Scatter(x=weekly.week, y=weekly.cum_median_ape * 100, name="cumulative", mode="lines+markers", line=dict(color=BLUE, width=2),
                   customdata=weekly.cum_n, hovertemplate="up to this week: %{y:.1f}% on %{customdata} listings<extra></extra>"),
    ])
    fig.add_hline(y=ERROR_ALERT * 100, line_dash="dash", line_color=RED, annotation_text=f"alert {ERROR_ALERT:.1%}", annotation_position="top left")
    fig.update_yaxes(title="median absolute % error of the price", rangemode="tozero")
    return styled(fig, "Median error of newly listed houses, weekly and cumulative", height=380, legend=True)


def city_bias_figure(by_city: pd.DataFrame) -> go.Figure:
    shown = by_city.sort_values("bias")
    fig = go.Figure(go.Bar(x=shown.bias * 100, y=[f"{c} (n={int(n)})" for c, n in zip(shown.index, shown.n)], orientation="h",
                           marker_color=[RED if abs(b) > CITY_BIAS_ALERT and n >= MIN_CITY_N else BLUE for b, n in zip(shown.bias, shown.n)],
                           hovertemplate="%{y}: median signed error %{x:+.1f}%<extra></extra>"))
    fig.add_vline(x=0, line_color=MUTED, line_width=1)
    fig.update_xaxes(title=f"median signed error (%): + means estimates too high; red beyond ±{CITY_BIAS_ALERT:.0%} with {MIN_CITY_N}+ listings")
    return styled(fig, "Bias by city on new listings", height=420)


def drift_figure(drift: pd.DataFrame) -> go.Figure:
    top = drift.head(12).iloc[::-1]
    fig = go.Figure(go.Bar(x=top.psi, y=top.feature, orientation="h", marker_color=[RED if p > PSI_ALERT else BLUE for p in top.psi],
                           hovertemplate="%{y}: PSI %{x:.3f}<extra></extra>"))
    fig.add_vline(x=PSI_ALERT, line_dash="dash", line_color=RED)
    fig.add_vline(x=0.1, line_dash="dot", line_color=MUTED)
    fig.update_xaxes(title="population stability index against the training rows (0.1: watch, 0.2: alert)")
    return styled(fig, "Input drift: the twelve features that moved most", height=420)


def city_mix_figure(reference: pd.DataFrame, new: pd.DataFrame) -> go.Figure:
    mix = pd.DataFrame({"training": reference.city.value_counts(normalize=True), "new": new.city.value_counts(normalize=True)}).fillna(0)
    mix = mix.sort_values("training")
    fig = go.Figure([go.Bar(x=mix.training * 100, y=mix.index, orientation="h", name="training", marker_color=GREY, hovertemplate="%{y}: %{x:.1f}%<extra>training</extra>"),
                     go.Bar(x=mix.new * 100, y=mix.index, orientation="h", name="new", marker_color=BLUE, hovertemplate="%{y}: %{x:.1f}%<extra>new</extra>")])
    fig.update_layout(barmode="group")
    fig.update_xaxes(title="share of listings (%)")
    return styled(fig, "City mix: training rows against new listings", height=460, legend=True)


def build_report(reference: pd.DataFrame, new: pd.DataFrame, estimate: np.ndarray, parse_rate: float | None = None,
                 date_col: str = "created_at", reference_estimate: np.ndarray | None = None) -> str:
    """HTML of the weekly report. `estimate` is the live model's price for each new listing; `reference_estimate` (out-of-fold
    estimates of the training rows) is optional and adds the check on predictions."""
    new = new.assign(estimate=estimate)
    new = new.assign(ape=(new.estimate - new.price).abs() / new.price, signed=(new.estimate - new.price) / new.price)
    weekly = weekly_table(new, date_col)
    by_city = new.groupby("city").agg(n=("ape", "size"), median_ape=("ape", "median"), bias=("signed", "median"))
    drift = drift_table(reference, new, [f for f in MODEL_FEATURES if f not in NOT_DRIFT_FEATURES])
    if reference_estimate is not None:
        drift = pd.concat([drift, pd.DataFrame([{"feature": "predicted price per m²", "psi": psi(pd.Series(reference_estimate) / reference.land_area.to_numpy(), new.estimate / new.land_area),
                                                  "ks": np.nan, "missing_ref": 0.0, "missing_now": 0.0}])]).sort_values("psi", ascending=False).reset_index(drop=True)
    alerts = alerts_for(weekly, by_city, drift, parse_rate)
    last = weekly.iloc[-1]
    judged = last.cum_n >= MIN_N
    figures = {"error": error_figure(weekly), "city_bias": city_bias_figure(by_city), "drift": drift_figure(drift), "mix": city_mix_figure(reference, new)}
    save_pngs(figures, ROOT / "reports" / "figures", "weekly")
    plot = plots_html(figures)
    tiles = [tile(f"{int(last.cum_n):,}", "new listings scored"),
             tile(f"{last.cum_median_ape:.1%}" if judged else "too few", f"cumulative median error (alert above {ERROR_ALERT:.1%}, judged from {MIN_N})"),
             tile(f"{last.cum_bias:+.1%}", f"bias (limit ±{BIAS_ALERT:.0%})"),
             tile(f"{drift.psi.max():.2f}", f"largest input PSI ({drift.feature.iloc[0]})"),
             tile("n/a" if parse_rate is None else f"{parse_rate:.0%}", f"parse rate (minimum {PARSE_MIN:.0%})"),
             tile(str(len(alerts)), "alerts")]
    alert_body = "<ul>" + "".join(f"<li>{a}</li>" for a in alerts) + "</ul>" if alerts else "<p>No alert fired.</p>"
    sections = [
        section("Alerts", "An alert opens an investigation; it never retrains the model by itself (the monthly challenger gate decides that).", alert_body),
        section("Performance on new listings", "The model scores houses it has never seen; the asking price is known as soon as the listing is crawled. "
                "Single weeks swing by several points, so only the cumulative line is judged.", plot["error"] + plot["city_bias"]),
        section("Input drift", "PSI compares each feature in the new listings with the training rows; the table lists the missing share too.",
                plot["drift"] + plot["mix"] + table_html(drift.head(15).round(3))),
        section("Thresholds", "Where the limits come from.", "<ul><li>Error: top of the holdout 95% interval (22.7%, 20.9 to 25.1%).</li>"
                "<li>Bias: the backtest stayed within ±5% every month.</li><li>PSI 0.2 is the usual alert level.</li>"
                "<li>Cumulative judgement from 200 listings: monthly error swung by about 3 points on 150 to 265 listings.</li></ul>"),
    ]
    subtitle = (f"New listings {new[date_col].min():%Y-%m-%d} to {new[date_col].max():%Y-%m-%d}, scored by the live model. "
                "Generated by <code>uv run python -m src.pipeline.weekly_report --simulate</code> (the pipeline will call the same function).")
    return page("Model health: weekly report", subtitle, tiles, sections)


if __name__ == "__main__":
    assert "--simulate" in sys.argv, "only the replay on the training part is wired up; the pipeline will call build_report"
    df = add_words(load_usable("train"))
    reference, new = df[df.created_at < pd.Timestamp(SIMULATE_CUTOFF, tz="UTC")], df[df.created_at >= pd.Timestamp(SIMULATE_CUTOFF, tz="UTC")]
    estimate = np.exp(fit_predict(reference, new)) * new.land_area.to_numpy()
    REPORT.write_text(build_report(reference, new, estimate), encoding="utf-8")
    print(f"wrote {REPORT} ({REPORT.stat().st_size / 1e6:.1f} MB): {len(reference)} reference rows, {len(new)} new listings")
