"""Deliverable mockup: one page with the median asking price per m² of land by kecamatan (default) or by H3 cell, resolution 7
(finer view). Equal-count colour classes so that outer areas stay readable next to central Jakarta; blank where fewer than 5
listings; kecamatan with a wide price spread are outlined as mixed. Aggregates only, no listing-level points.
Writes reports/price_map.html and PNGs of both views."""

import json

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.colors import sample_colorscale

from src.analysis.html_report import BLUES, page, plots_html, section, styled, table_html, tile
from src.config import ROOT, SPATIAL
from src.features.aggregate import H3_RESOLUTION, MIN_LISTINGS, all_usable, h3_prices, kecamatan_prices

REPORT = ROOT / "reports" / "price_map.html"
FIGURES = ROOT / "reports" / "figures"
EMPTY = "#e6e8ec"
CLASSES = 7
MIXED_SPREAD = 2.5  # 75th / 25th percentile price per m²: above this the median is not one typical price


def class_edges(values: pd.Series) -> np.ndarray:
    """Quantile edges of the kecamatan medians (M IDR/m²), rounded to readable steps."""
    raw = np.quantile(values, np.linspace(0, 1, CLASSES + 1))
    step = np.where(raw < 10, 0.5, np.where(raw < 30, 1, 5))
    return np.unique(np.round(raw / step) * step)


def colorscale(n: int) -> tuple[list, list[str]]:
    colors = sample_colorscale(BLUES, np.linspace(0.06, 1, n))
    stops = [stop for i, color in enumerate(colors) for stop in ((i / n, color), ((i + 1) / n, color))]
    return stops, colors


def labels(edges: np.ndarray) -> list[str]:
    inner = [f"{a:g}–{b:g}" for a, b in zip(edges[1:-2], edges[2:-1])]
    return [f"under {edges[1]:g}", *inner, f"{edges[-2]:g} and over"]


def classes(median_m: pd.Series, edges: np.ndarray) -> np.ndarray:
    return np.digitize(median_m, edges[1:-1]) + 0.5


def layer_traces(shown: pd.DataFrame, blank: pd.DataFrame, geojson: dict, id_key: str | None, edges: np.ndarray, hover_shown: str, hover_blank: str,
                 shown_data: pd.DataFrame, blank_data: pd.DataFrame, line_width: float) -> list[go.Choropleth]:
    n = len(edges) - 1
    scale, _ = colorscale(n)
    common = dict(geojson=geojson, **({"featureidkey": id_key} if id_key else {}), marker_line_color="white", marker_line_width=line_width)
    return [
        go.Choropleth(**common, locations=blank.id, z=[0] * len(blank), colorscale=[[0, EMPTY], [1, EMPTY]], showscale=False,
                      customdata=blank_data, hovertemplate=hover_blank),
        go.Choropleth(**common, locations=shown.id, z=classes(shown.median_m, edges), zmin=0, zmax=n, colorscale=scale,
                      colorbar=dict(title="M IDR/m²", thickness=12, len=0.7, tickmode="array", tickvals=np.arange(n) + 0.5, ticktext=labels(edges)),
                      customdata=shown_data, hovertemplate=hover_shown),
    ]


def build(kec: pd.DataFrame, cells: pd.DataFrame, kec_geo: dict, edges: np.ndarray, which: str) -> go.Figure:
    kec = kec.assign(id=kec.kdcpum, median_m=kec.median_ppm2_land / 1e6)
    cells = cells.assign(id=cells.cell, median_m=cells.median_ppm2_land / 1e6)
    k_shown, k_blank = kec[kec.median_m.notna()], kec[kec.median_m.isna()]
    c_shown, c_blank = cells[cells.median_m.notna()], cells[cells.median_m.isna()]
    spread = (k_shown.p75_ppm2_land / k_shown.p25_ppm2_land).round(1)
    k_data = k_shown.assign(p25=k_shown.p25_ppm2_land / 1e6, p75=k_shown.p75_ppm2_land / 1e6, spread=spread,
                            note=np.where(spread > MIXED_SPREAD, "<br><b>mixed prices: the middle half spans " + spread.astype(str) + "x</b>", ""))
    c_data = c_shown.assign(p25=c_shown.p25_ppm2_land / 1e6, p75=c_shown.p75_ppm2_land / 1e6)
    kecamatan = layer_traces(
        k_shown, k_blank, kec_geo, "properties.kdcpum", edges,
        "<b>%{customdata[0]}</b>, %{customdata[1]}<br>median %{z:.0f}<extra></extra>", "", k_data[["wadmkc", "wadmkk", "listings", "p25", "p75", "note"]],
        k_blank[["wadmkc", "wadmkk", "listings"]].fillna(0), 0.5)
    kecamatan[1].hovertemplate = ("<b>%{customdata[0]}</b>, %{customdata[1]}<br>median %{text} M IDR/m² of land<br>middle half %{customdata[3]:.1f} to %{customdata[4]:.1f}"
                                  "<br>%{customdata[2]} listings%{customdata[5]}<extra></extra>")
    kecamatan[1].text = [f"{v:.1f}" for v in k_shown.median_m]
    kecamatan[0].hovertemplate = f"<b>%{{customdata[0]}}</b>, %{{customdata[1]}}<br>%{{customdata[2]:.0f}} listings: fewer than {MIN_LISTINGS}, no median<extra></extra>"
    mixed = k_shown[spread > MIXED_SPREAD]
    outline = go.Choropleth(geojson=kec_geo, featureidkey="properties.kdcpum", locations=mixed.id, z=[0] * len(mixed), showscale=False,
                            colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]], marker_line_color="#1f2933", marker_line_width=1.8, hoverinfo="skip")
    cell_geo = {"type": "FeatureCollection", "features": [{"type": "Feature", "id": c, "properties": {}, "geometry": {"type": "Polygon",
                "coordinates": [[(lng, lat) for lat, lng in h3.cell_to_boundary(c)] + [h3.cell_to_boundary(c)[0][::-1]]]}} for c in cells.cell]}
    finer = layer_traces(c_shown, c_blank, cell_geo, None, edges, "", "", c_data[["listings", "p25", "p75"]], c_blank[["listings"]], 0)
    finer[1].hovertemplate = "median %{text} M IDR/m² of land<br>middle half %{customdata[1]:.1f} to %{customdata[2]:.1f}<br>%{customdata[0]} listings<extra></extra>"
    finer[1].text = [f"{v:.1f}" for v in c_shown.median_m]
    finer[0].hovertemplate = f"%{{customdata[0]}} listings: fewer than {MIN_LISTINGS}, no median<extra></extra>"
    guide = go.Choropleth(geojson=kec_geo, featureidkey="properties.kdcpum", locations=kec.id, z=[0] * len(kec), showscale=False,
                          colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]], marker_line_color="#9aa3af", marker_line_width=0.4, hoverinfo="skip")
    groups = {"kecamatan": [*kecamatan, outline], "h3": [*finer, guide]}
    traces = [t for key in ("kecamatan", "h3") for t in groups[key]] if which == "both" else groups[which]
    fig = go.Figure(traces)
    fig.update_geos(fitbounds="locations", visible=False, bgcolor="rgba(0,0,0,0)")
    fig.update_layout(margin=dict(l=0, r=0, b=0))
    title = {"kecamatan": f"Median asking price per m² of land by kecamatan (grey: fewer than {MIN_LISTINGS} listings; dark outline: mixed prices)",
             "h3": f"Median asking price per m² of land by H3 cell, resolution {H3_RESOLUTION} (grey: fewer than {MIN_LISTINGS} listings)",
             "both": "Median asking price per m² of land (equal-count colour classes; grey: fewer than 5 listings)"}[which]
    fig = styled(fig, title, height=580)
    if which == "both":
        nk, nh = len(groups["kecamatan"]), len(groups["h3"])
        fig.update_layout(updatemenus=[dict(type="buttons", direction="right", x=1, xanchor="right", y=1.02, yanchor="bottom", buttons=[
            dict(label="Kecamatan", method="update", args=[{"visible": [True] * nk + [False] * nh}]),
            dict(label="H3 finer view", method="update", args=[{"visible": [False] * nk + [True] * nh}])])])
        for i in range(nk, nk + nh):
            fig.data[i].visible = False
    return fig


if __name__ == "__main__":
    df = all_usable()
    kec = gpd.read_file(SPATIAL / "big_kecamatan_jabodetabek.geojson")[["kdcpum", "wadmkc", "wadmkk", "geometry"]]
    kec_geo = json.loads(kec.to_json())
    prices = kecamatan_prices(df).drop(columns="kecamatan")
    kec = pd.DataFrame(kec.drop(columns="geometry")).merge(prices, left_on="kdcpum", right_on="kecamatan_code", how="left")
    kec["listings"] = kec.listings.fillna(0).astype(int)
    cells = h3_prices(df)
    shown = kec[kec.median_ppm2_land.notna()]
    edges = class_edges(shown.median_ppm2_land / 1e6)
    FIGURES.mkdir(parents=True, exist_ok=True)
    for which in ("kecamatan", "h3"):
        build(kec, cells, kec_geo, edges, which).write_image(FIGURES / f"price_map_{which}.png", width=1000, height=580, scale=2)
    figures = {"price_map": build(kec, cells, kec_geo, edges, "both")}
    plot = plots_html(figures)
    spread = (shown.p75_ppm2_land / shown.p25_ppm2_land)
    table = (shown.assign(spread=spread.round(1)).sort_values("median_ppm2_land", ascending=False)
             [["wadmkc", "wadmkk", "listings", "median_ppm2_land", "p25_ppm2_land", "p75_ppm2_land", "spread", "median_ppm2_building"]]
             .rename(columns={"wadmkc": "kecamatan", "wadmkk": "city", "median_ppm2_land": "median IDR/m² land", "p25_ppm2_land": "25th pct",
                              "p75_ppm2_land": "75th pct", "spread": "75th / 25th", "median_ppm2_building": "median IDR/m² building"}))
    sections = [
        section("Map", f"{len(shown)} of {len(kec)} kecamatan have {MIN_LISTINGS}+ listings and show a median (colours are equal-count classes, so each step holds "
                f"about the same number of areas; the legend gives the Rp/m² range). {int((spread > MIXED_SPREAD).sum())} are outlined as mixed prices: the middle "
                f"half of their listings spans more than {MIXED_SPREAD}x. The H3 view is finer (cells of about 5 km²) but covers fewer listings.", plot["price_map"]),
        section("Table", "Observed medians of asking prices by kecamatan, dearest first; 75th / 25th is the spread of the middle half of listings. "
                "Asking prices run above transaction prices.", table_html(table.round(0))),
    ]
    tiles = [
        tile(f"{len(shown)} / {len(kec)}", f"kecamatan with {MIN_LISTINGS}+ listings"),
        tile(f"{kec.listings[shown.index].sum() / kec.listings.sum():.0%}", "of listings in a shown kecamatan"),
        tile(f"{int((spread > MIXED_SPREAD).sum())}", "kecamatan with mixed prices"),
        tile(f"{int(cells.median_ppm2_land.notna().sum())}", f"H3 cells with {MIN_LISTINGS}+ listings"),
    ]
    subtitle = ("MOCKUP of the Phase 1 deliverable. Portal asking prices, all usable listings; observed medians, not model predictions. "
                "Generated by <code>uv run python -m src.analysis.price_map</code>.")
    REPORT.write_text(page("Jabodetabek price per m² by area", subtitle, tiles, sections), encoding="utf-8")
    print(f"wrote {REPORT} ({REPORT.stat().st_size / 1e6:.1f} MB); class edges (M IDR/m²): {edges}")
