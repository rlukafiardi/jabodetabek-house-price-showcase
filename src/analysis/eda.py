"""EDA on the training part only: one self-contained HTML report (reports/eda.html), PNG copies of every chart
(reports/figures/eda_*.png) and CSV tables (reports/tables/eda_*.csv)."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.stats import spearmanr
from sklearn.linear_model import LinearRegression
from sklearn.neighbors import BallTree

from src.analysis.html_report import BLUE, BLUES, DIVERGING, GREY, MUTED, RED, page, plots_html, save_pngs, section, styled, table_html, tile
from src.analysis.noise_floor import noise_table
from src.config import INTERIM, ROOT
from src.features.spatial import EARTH_RADIUS_KM
from src.ingestion.parse import FACILITY_FLAGS, TEXT_FLAGS
from src.ingestion.validate import waterfall
from src.modeling.dataset import load_usable

REPORT = ROOT / "reports" / "eda.html"
FIGURES = ROOT / "reports" / "figures"
TABLES = ROOT / "reports" / "tables"
KECAMATAN_TOTAL = 183
BANDS_KM = [(0, 1), (1, 2), (2, 5), (5, 10), (10, 20)]
OUTLIER_Z = 3.5  # robust z-score of log price per m² within the city
LABELS = {
    "log_land": "land area (log)", "log_building": "building area (log)", "bedrooms": "bedrooms", "bathrooms": "bathrooms",
    "floors": "floors", "age_days": "listing age (days)", "flood_index": "flood hazard index", "dist_station_km": "km to rail station", "dist_krl_km": "km to KRL station",
    "dist_mrt_lrt_km": "km to MRT/LRT", "dist_busway_km": "km to busway stop", "dist_toll_km": "km to toll gate",
    "dist_monas_km": "km to Monas", "dist_mall_km": "km to mall", "dist_hospital_km": "km to hospital",
    "dist_university_km": "km to university", "lat": "latitude", "lon": "longitude",
    "spec_electricity_va": "electricity (VA)", "spec_carport": "carport spaces", "spec_car_access": "cars that fit the access road",
    "spec_furnished_level": "furnished level (0-2)", "fac_count": "facilities listed (count)",
    "dist_cbd_km": "km to nearest CBD core", "dist_center_km": "km to nearest business centre", "dist_primary_road_km": "km to primary road",
    "dist_secondary_road_km": "km to secondary road", "dist_tertiary_road_km": "km to tertiary road",
    "share_residential_500m": "residential land within 500 m", "share_commercial_500m": "commercial land within 500 m",
    "share_industrial_500m": "industrial land within 500 m", "dist_industrial_km": "km to industrial land", "dist_river_km": "km to river or canal",
    "dist_rail_line_km": "km to railway line", "dist_power_line_km": "km to power line",
    "n_rail_1km": "rail stations within 1 km", "n_rail_2km": "rail stations within 2 km", "n_busway_500m": "busway stops within 500 m",
    "n_busway_1km": "busway stops within 1 km", "n_mall_2km": "malls within 2 km", "n_hospital_2km": "hospitals within 2 km",
    "n_university_2km": "universities within 2 km", "flood_mean_500m": "flood index, 500 m mean",
}
TARGET_LABEL = "price per m² of land (log)"
DICTIONARY = [  # column, meaning, unit, source
    ("price", "asking price", "IDR", "Portal listing"),
    ("land_area", "plot size", "m²", "Portal listing"),
    ("building_area", "floor area summed over all floors (not the footprint)", "m²", "Portal listing"),
    ("bedrooms, bathrooms, floors", "room and floor counts; floors is sometimes missing", "count", "Portal listing"),
    ("certificate", "land title: SHM freehold, HGB right to build, girik customary, lainnya other", "category", "Portal listing"),
    ("lat, lon", "listing coordinate, or the district centroid when the agent gave none", "degrees", "Portal listing"),
    ("coord_is_centroid", "1 when the coordinate equals the district centroid", "flag", "derived"),
    ("created_at, age_days", "listing creation date and its age", "date, days", "Portal listing"),
    ("txt_* (13 flags)", "keywords in the title or description: auction, new, luxury, needs work, ...", "flag", "derived from text"),
    ("kecamatan", "BIG kecamatan that contains the coordinate", "category", "BIG boundaries"),
    ("dist_*_km", "distance to the nearest rail station, KRL, MRT/LRT, busway stop, toll gate, mall, hospital, university, Monas", "km", "OpenStreetMap"),
    ("flood_index", "flood hazard index at the coordinate", "0 to 1", "BNPB InaRISK"),
    ("n_rail_1km, n_rail_2km, n_busway_500m, n_busway_1km, n_mall_2km, n_hospital_2km, n_university_2km",
     "buffer counts: rail stations, busway stops, malls, hospitals, universities within the radius", "count", "OpenStreetMap"),
    ("flood_mean_500m", "mean flood hazard index of the raster cells within 500 m (buffer)", "0 to 1", "BNPB InaRISK"),
    ("spec_electricity_va, spec_carport, spec_car_access, spec_garage, spec_maid_rooms",
     "numeric specs filled in by the agent (most are missing for 60% or more of listings)", "VA, count", "Portal listing"),
    ("spec_furnished_level, spec_water_pam", "furnished: 0 none, 1 semi, 2 fully; water source: 1 PAM mains, 0 groundwater", "level, flag", "Portal listing"),
    ("fac_* (12 flags), fac_count", "facilities ticked by the agent (security, AC, kitchen set, garden, balcony, pool, gym, elevator, CCTV, jogging track, ...); absent counts as 0", "flag, count", "Portal listing"),
    ("dist_cbd_km, dist_center_km", "km to the nearest of SCBD, Kuningan, Thamrin; km to the nearest of 13 business centres (approximate coordinates)", "km", "derived"),
    ("dist_*_road_km, dist_river_km, dist_rail_line_km, dist_power_line_km, dist_industrial_km",
     "km to the nearest major road of each class, river or canal, railway line, power line, industrial land", "km", "OpenStreetMap"),
    ("share_residential_500m, share_commercial_500m, share_industrial_500m", "share of the 500 m disk that is mapped as that land use (patchy in outer areas)", "0 to 1", "OpenStreetMap"),
    ("target", "log(price / land_area)", "log IDR per m²", "derived"),
]

def moran_band(values: np.ndarray, coords: np.ndarray, lo_km: float, hi_km: float) -> float:
    """Moran's I with binary weights for pairs whose distance is in (lo, hi] km, row-standardised."""
    tree = BallTree(np.radians(coords), metric="haversine")
    outer = tree.query_radius(np.radians(coords), r=hi_km / EARTH_RADIUS_KM, return_distance=True)
    pairs = [(i, j) for i, (idx, dist) in enumerate(zip(*outer)) for j, d in zip(idx, dist) if lo_km < d * EARTH_RADIUS_KM <= hi_km]
    rows, cols = np.array(pairs).T
    w = 1.0 / np.bincount(rows, minlength=len(values))[rows]
    with_neighbours = np.unique(rows)
    z = values - values.mean()
    return float(len(values) / len(with_neighbours) * np.sum(w * z[rows] * z[cols]) / np.sum(z[with_neighbours] ** 2))


def city_residual(df: pd.DataFrame) -> pd.Series:
    """Log price per m² minus the city median: compares listings within their own city."""
    return np.log(df.ppm2_land) - df.groupby("city").ppm2_land.transform(lambda s: np.log(s).median())


def column_kind(s: pd.Series) -> str:
    if pd.api.types.is_datetime64_any_dtype(s):
        return "date"
    if pd.api.types.is_bool_dtype(s) or (pd.api.types.is_numeric_dtype(s) and set(s.dropna().unique()) <= {0, 1}):
        return "flag"
    return "numeric" if pd.api.types.is_numeric_dtype(s) else "categorical"


def profile(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Per-column overview, numeric statistics and categorical top values. slug is a listing identifier, so it is left out."""
    columns = [c for c in df.columns if c != "slug"]
    overview, numeric, categorical = [], [], []
    for c in columns:
        s, kind = df[c], column_kind(df[c])
        overview.append({"column": c, "dtype": str(s.dtype), "kind": kind, "non-null": int(s.notna().sum()), "missing": int(s.isna().sum()),
                         "missing %": s.isna().mean() * 100, "distinct": int(s.nunique()), "constant": s.nunique() <= 1})
        if kind in ("numeric", "flag"):
            s = s.astype(float)
            q = s.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
            numeric.append({"column": c, "kind": kind, "mean": s.mean(), "std": s.std(), "min": s.min(), "p5": q[0.05], "p25": q[0.25],
                            "median": q[0.5], "p75": q[0.75], "p95": q[0.95], "max": s.max(), "skew": s.skew(), "zeros %": (s == 0).mean() * 100})
        elif kind == "categorical":
            counts = s.value_counts()
            top = ", ".join(f"{v} ({n / s.notna().sum():.0%})" for v, n in counts.head(3).items())
            categorical.append({"column": c, "distinct": len(counts), "top value": counts.index[0], "top value %": counts.iloc[0] / s.notna().sum() * 100,
                                "top 3": top, "rare (<1%) values": int((counts / s.notna().sum() < 0.01).sum())})
    return pd.DataFrame(overview), pd.DataFrame(numeric), pd.DataFrame(categorical)


def target_histogram(df: pd.DataFrame) -> go.Figure:
    edges = np.logspace(np.log10(df.ppm2_land.min()), np.log10(df.ppm2_land.max()), 31) / 1e6
    counts, _ = np.histogram(df.ppm2_land / 1e6, bins=edges)
    labels = [f"{a:.1f}-{b:.1f}" for a, b in zip(edges[:-1], edges[1:])]
    fig = go.Figure(go.Bar(x=labels, y=counts, marker_color=BLUE, hovertemplate="%{x} M IDR/m²: %{y} listings<extra></extra>"))
    fig.update_xaxes(title="price per m² of land, million IDR (log-spaced bins)", tickangle=-45, nticks=12)
    fig.update_yaxes(title="listings")
    return styled(fig, "Price per m² of land is right-skewed and close to log-normal")


def city_ranges(df: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    city = df.groupby("city").ppm2_land.agg(n="size", median="median", q25=lambda s: s.quantile(0.25), q75=lambda s: s.quantile(0.75))
    city = (city / [1, 1e6, 1e6, 1e6]).sort_values("median")
    xs, ys = [], []
    for name, row in city.iterrows():
        xs += [row.q25, row.q75, None]
        ys += [name, name, None]
    fig = go.Figure([
        go.Scatter(x=xs, y=ys, mode="lines", line=dict(color=GREY, width=8), hoverinfo="skip"),
        go.Scatter(x=city["median"], y=city.index, mode="markers", marker=dict(color=BLUE, size=11, line=dict(color="white", width=2)),
                   customdata=np.c_[city.n, city.q25, city.q75],
                   hovertemplate="%{y}<br>median %{x:.1f} M IDR/m²<br>middle half %{customdata[1]:.1f}-%{customdata[2]:.1f}<br>%{customdata[0]} listings<extra></extra>"),
    ])
    fig.update_xaxes(title="million IDR per m² of land: median (dot) and middle half of listings (bar)")
    return styled(fig, "Price per m² differs several-fold between cities", height=460), city


def target_correlations(df: pd.DataFrame) -> tuple[go.Figure, pd.Series]:
    rho = pd.Series({f: spearmanr(df[f], df.y, nan_policy="omit")[0] for f in LABELS}).sort_values()
    fig = go.Figure(go.Bar(x=rho.values, y=[LABELS[f] for f in rho.index], orientation="h", marker_color=[RED if v < 0 else BLUE for v in rho],
                           hovertemplate="%{y}: Spearman %{x:.2f}<extra></extra>"))
    fig.update_xaxes(title=f"Spearman correlation with {TARGET_LABEL}", range=[-1, 1])
    return styled(fig, "Which features move with price (red: price falls as the value rises)", height=max(560, 22 * len(rho) + 110)), rho


def bivariate(df: pd.DataFrame) -> go.Figure:
    fig = make_subplots(rows=2, cols=2, horizontal_spacing=0.1, vertical_spacing=0.16,
                        subplot_titles=["land area (m², log)", "building area (m², log)", "km to Monas", "floors"])
    y = df.ppm2_land / 1e6
    hover = "%{x:.0f} → %{y:.1f} M IDR/m²<extra></extra>"
    for (r, c), x in zip([(1, 1), (1, 2), (2, 1)], [df.land_area, df.building_area, df.dist_monas_km]):
        fig.add_trace(go.Scatter(x=x, y=y, mode="markers", marker=dict(color=BLUE, size=5, opacity=0.45), hovertemplate=hover), row=r, col=c)
    for floors, part in df.dropna(subset=["floors"]).groupby("floors"):
        if len(part) >= 5:
            fig.add_trace(go.Box(x=[f"{floors:.0f}"] * len(part), y=part.ppm2_land / 1e6, marker_color=BLUE, boxpoints=False, name=f"{floors:.0f}"), row=2, col=2)
    area_ticks = [20, 50, 100, 200, 500, 1000, 2000]
    fig.update_xaxes(type="log", tickvals=area_ticks, ticktext=[str(t) for t in area_ticks], row=1, col=1)
    fig.update_xaxes(type="log", tickvals=area_ticks, ticktext=[str(t) for t in area_ticks], row=1, col=2)
    price_ticks = [1, 2, 5, 10, 20, 50, 100]
    fig.update_yaxes(type="log", tickvals=price_ticks, ticktext=[str(t) for t in price_ticks], title="M IDR per m² of land")
    return styled(fig, "Price per m² against the strongest features", height=640)


def flag_effects(df: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    """Median price difference within city when a flag is present (or a title type, versus SHM), for groups of 5+ listings."""
    resid = city_residual(df)
    rows = [(name.removeprefix("txt_").replace("_", " "), int(df[name].sum()), np.exp(resid[df[name] == 1].median() - resid[df[name] == 0].median()) - 1)
            for name in TEXT_FLAGS if df[name].sum() >= 5]
    rows += [(f"facility: {name.removeprefix('fac_').replace('_', ' ')}", int(df[name].sum()), np.exp(resid[df[name] == 1].median() - resid[df[name] == 0].median()) - 1)
             for name in (f"fac_{f}" for f in FACILITY_FLAGS) if df[name].sum() >= 5]
    title = df.certificate.str.removeprefix("property_certificate.").fillna("missing")
    rows += [(f"title {t.upper()} vs SHM", int((title == t).sum()), np.exp(resid[title == t].median() - resid[title == "shm"].median()) - 1)
             for t in title.unique() if t != "shm" and (title == t).sum() >= 5]
    table = pd.DataFrame(rows, columns=["feature", "listings", "price difference"]).sort_values("price difference")
    fig = go.Figure(go.Bar(x=table["price difference"] * 100, y=[f"{f} ({n})" for f, n in zip(table.feature, table.listings)],
                           orientation="h", customdata=table.listings,
                           marker_color=[RED if v < 0 else BLUE for v in table["price difference"]],
                           hovertemplate="%{y}: %{x:+.0f}% (%{customdata} listings)<extra></extra>"))
    fig.update_xaxes(title="median price per m² difference within the same city (%)")
    return styled(fig, "Text flags, facilities and land title: how much cheaper or dearer, within city (listings in brackets)", height=max(460, 22 * len(table) + 110)), table


def feature_matrix(df: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    columns = list(LABELS) + ["y"]
    names = [LABELS[c] for c in LABELS] + [TARGET_LABEL]
    corr = df[columns].corr(method="spearman").to_numpy()
    fig = go.Figure(go.Heatmap(z=corr, x=names, y=names, zmin=-1, zmax=1, colorscale=DIVERGING, texttemplate="%{z:.1f}",
                               textfont=dict(size=9), colorbar=dict(title="Spearman", thickness=12),
                               hovertemplate="%{y}<br>%{x}<br>Spearman %{z:.2f}<extra></extra>"))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(tickangle=-90)
    upper = [(names[i], names[j], corr[i, j]) for i in range(len(names)) for j in range(i + 1, len(names)) if abs(corr[i, j]) >= 0.7]
    pairs = pd.DataFrame(upper, columns=["feature", "other feature", "spearman"]).sort_values("spearman", key=abs, ascending=False)
    fig = styled(fig, "Correlation between features (blue: rise together, red: opposite)", height=max(780, 24 * len(LABELS) + 330))
    fig.update_layout(margin=dict(l=10, r=10, t=56, b=250))
    return fig, pairs


def variance_inflation(df: pd.DataFrame) -> pd.DataFrame:
    """VIF = 1 / (1 - R²) of each feature regressed on all the others (median-imputed): above ~10 the feature is mostly redundant."""
    x = df[list(LABELS)].fillna(df[list(LABELS)].median())
    vif = {LABELS[c]: 1 / (1 - LinearRegression().fit(x.drop(columns=c), x[c]).score(x.drop(columns=c), x[c])) for c in x}
    return pd.Series(vif, name="VIF").sort_values(ascending=False).round(1).reset_index().rename(columns={"index": "feature"})


def missing_bars(df: pd.DataFrame) -> go.Figure:
    columns = ["floors", "certificate", "sub_district", "district", "spec_electricity_va", "spec_carport", "spec_car_access",
               "spec_water_pam", "spec_garage", "spec_maid_rooms"]
    share = df[columns].isna().mean().sort_values() * 100
    fig = go.Figure(go.Bar(x=share.values, y=share.index, orientation="h", marker_color=BLUE, text=[f"{v:.1f}%" for v in share],
                           textposition="outside", hovertemplate="%{y}: %{x:.1f}% missing<extra></extra>"))
    fig.update_xaxes(title="share of training listings missing (%)", range=[0, max(share.max() * 1.3, 5)])
    return styled(fig, "Missing values by field", height=380)


def outliers(df: pd.DataFrame) -> pd.DataFrame:
    log_ppm2 = np.log(df.ppm2_land)
    by_city = log_ppm2.groupby(df.city)
    z = (log_ppm2 - by_city.transform("median")) / (1.4826 * by_city.transform(lambda s: (s - s.median()).abs().median()))
    flagged = df.assign(z=z)[z.abs() > OUTLIER_Z]
    return flagged.assign(price_M=flagged.price / 1e6, ppm2_M=flagged.ppm2_land / 1e6)[
        ["city", "land_area", "building_area", "floors", "price_M", "ppm2_M", "z"]].sort_values("z").round(1)


def listing_map(df: pd.DataFrame) -> go.Figure:
    own = df[df.coord_is_centroid == 0]
    stacked = df[df.coord_is_centroid == 1].groupby(["lat", "lon"]).agg(n=("price", "size"), district=("district", "first")).reset_index()
    fig = go.Figure([
        go.Scatter(x=stacked.lon, y=stacked.lat, mode="markers", name="district-centroid coordinates (size = listings)",
                   marker=dict(symbol="square", color=GREY, size=6 + 3 * np.sqrt(stacked.n)), customdata=np.c_[stacked.district, stacked.n],
                   hovertemplate="%{customdata[0]}: %{customdata[1]} listings at the district centroid<extra></extra>"),
        go.Scatter(x=own.lon, y=own.lat, mode="markers", name="own coordinates (colour = price per m²)",
                   marker=dict(size=7, color=np.log10(own.ppm2_land / 1e6), colorscale=BLUES, line=dict(color="white", width=0.5),
                               colorbar=dict(title="M IDR/m²", thickness=12, tickvals=np.log10([5, 10, 20, 40, 80]), ticktext=["5", "10", "20", "40", "80"])),
                   customdata=np.c_[own.city, own.ppm2_land / 1e6], hovertemplate="%{customdata[0]}<br>%{customdata[1]:.1f} M IDR/m²<extra></extra>"),
    ])
    fig.update_xaxes(title="longitude", range=[106.35, 107.25])
    fig.update_yaxes(title="latitude", range=[-6.75, -5.95], scaleanchor="x", scaleratio=1 / np.cos(np.radians(6.2)))
    return styled(fig, "Where the training listings are, and how precise the location is", height=640, legend=True)


def moran_lines(moran: pd.DataFrame) -> go.Figure:
    fig = go.Figure([
        go.Scatter(x=moran.band_km, y=moran.moran_raw, mode="lines+markers", name="raw", line=dict(color=BLUE, width=2), marker=dict(size=9),
                   hovertemplate="%{x} km: Moran's I %{y:.2f}<extra>raw</extra>"),
        go.Scatter(x=moran.band_km, y=moran.moran_city_adjusted, mode="lines+markers", name="city median removed", line=dict(color=MUTED, width=2),
                   marker=dict(size=9), hovertemplate="%{x} km: Moran's I %{y:.2f}<extra>city median removed</extra>"),
    ])
    fig.add_hline(y=0, line_color=MUTED, line_width=1)
    fig.update_xaxes(title="distance between listings (km)")
    fig.update_yaxes(title="Moran's I")
    return styled(fig, "Neighbouring prices are alike up to ~5 km, and independent beyond ~10 km", legend=True)


def month_line(by_month: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Scatter(x=by_month.index, y=by_month.resid, mode="lines+markers", line=dict(color=BLUE, width=2), marker=dict(size=8),
                               customdata=by_month.n, hovertemplate="%{x}: %{y:+.2f} (%{customdata} listings)<extra></extra>"))
    fig.add_hline(y=0, line_color=MUTED, line_width=1)
    fig.update_yaxes(title="vs city median (log)")
    return styled(fig, "No clear trend by listing month (log price per m², city median removed)", height=320)


if __name__ == "__main__":
    for folder in (FIGURES, TABLES):
        folder.mkdir(parents=True, exist_ok=True)
    df = load_usable()
    df = df.assign(ppm2_land=df.price / df.land_area, month=df.created_at.dt.strftime("%Y-%m"))

    own = df[df.coord_is_centroid == 0]
    coords, adjusted = own[["lat", "lon"]].to_numpy(), city_residual(own).to_numpy()
    moran = pd.DataFrame([{"band_km": f"{lo}-{hi}", "moran_raw": moran_band(np.log(own.ppm2_land).to_numpy(), coords, lo, hi),
                           "moran_city_adjusted": moran_band(adjusted, coords, lo, hi)} for lo, hi in BANDS_KM])
    by_month = df.assign(resid=city_residual(df)).groupby("month").agg(n=("resid", "size"), resid=("resid", "mean"))
    kecamatan = df.groupby("kecamatan_code").size()
    steps = pd.DataFrame(waterfall(pd.read_csv(INTERIM / "portal_listings.csv")), columns=["step", "listings left"])
    vif = variance_inflation(df)
    flagged = outliers(df)
    noise = noise_table()
    overview, numeric_stats, categorical_stats = profile(df)

    figures = {}
    figures["target"] = target_histogram(df)
    figures["city"], city = city_ranges(df)
    figures["target_corr"], rho = target_correlations(df)
    figures["bivariate"] = bivariate(df)
    figures["flags"], flags = flag_effects(df)
    figures["matrix"], pairs = feature_matrix(df)
    figures["missing"] = missing_bars(df)
    figures["map"] = listing_map(df)
    figures["moran"] = moran_lines(moran)
    figures["month"] = month_line(by_month)
    save_pngs(figures, FIGURES, "eda")
    for name, table in {"eda_city": city.round(2), "eda_spearman": rho.round(3).rename("spearman").to_frame(), "eda_correlated_pairs": pairs.round(3),
                        "eda_vif": vif, "eda_flags": flags.round(3), "eda_outliers": flagged, "eda_moran": moran.round(3), "eda_month": by_month.round(3),
                        "eda_noise_floor": noise.round(3), "eda_profile": overview.round(2), "eda_profile_numeric": numeric_stats.round(3), "eda_profile_categorical": categorical_stats.round(2)}.items():
        table.to_csv(TABLES / f"{name}.csv")

    plot = plots_html(figures)
    floors_missing = df.floors.isna()
    ratio = (df.building_area / df.land_area).groupby(df.floors).median()
    high_vif = vif[vif.VIF >= 10]
    strongest_flag = flags.iloc[flags["price difference"].abs().argmax()]
    with_missing = overview[overview.missing > 0]
    sections = [
        section("Data dictionary", "What each column means, its unit and where it comes from.",
                table_html(pd.DataFrame(DICTIONARY, columns=["column", "meaning", "unit", "source"]))),
        section("Data profile", f"{len(df):,} rows, {len(overview)} columns: {(overview.kind == 'numeric').sum()} numeric, "
                f"{(overview.kind == 'flag').sum()} flags, {(overview.kind == 'categorical').sum()} categorical, {(overview.kind == 'date').sum()} date. "
                f"{len(with_missing)} have missing values ({', '.join(with_missing.column)}); {int(overview.constant.sum())} are constant "
                f"({', '.join(overview.column[overview.constant])}). The listing identifier is left out.",
                table_html(overview) + "<h3>Numeric columns and flags</h3>" + table_html(numeric_stats) +
                "<h3>Categorical columns</h3>" + table_html(categorical_stats)),
        section("Target", f"Median {df.ppm2_land.median() / 1e6:.1f} M IDR per m² of land; skew {df.ppm2_land.skew():.1f} raw vs "
                f"{np.log(df.ppm2_land).skew():.2f} on the log scale, so the model works on log price per m².", plot["target"]),
        section("Cities", f"Medians run from {city['median'].min():.1f} M ({city['median'].idxmin()}) to {city['median'].max():.1f} M "
                f"({city['median'].idxmax()}). Thin cities: {', '.join(f'{c} ({n})' for c, n in city.n[city.n < 30].items())}.", plot["city"]),
        section("Features vs price", f"Strongest: {LABELS[rho.abs().idxmax()]} ({rho[rho.abs().idxmax()]:+.2f}). The flood index"
                f" is positive only because central Jakarta is both flood-prone and expensive.",
                plot["target_corr"] + plot["bivariate"]),
        section("Text flags, facilities and land title", f"Largest within-city difference: {strongest_flag.feature} "
                f"({strongest_flag['price difference']:+.0%}, {strongest_flag.listings} listings).", plot["flags"]),
        section("Feature correlations", f"{len(pairs)} pairs move together strongly (|Spearman| at least 0.7) and {len(high_vif)} features have a VIF of "
                "10 or more: redundant for a linear model, whose coefficients for them cannot be read on their own. Trees cope.",
                plot["matrix"] + table_html(pairs.round(2)) + table_html(vif.head(10))),
        section("Missing values", f"Floors missing for {floors_missing.mean():.0%} of listings, and those listings are cheaper "
                f"({df.ppm2_land[floors_missing].median() / 1e6:.1f} vs {df.ppm2_land[~floors_missing].median() / 1e6:.1f} M IDR/m²): "
                "not random, so the model gets a missing flag, not an imputed value. "
                f"The agent-filled specs are mostly empty (electricity missing for {df.spec_electricity_va.isna().mean():.0%}), and listings that fill it in "
                f"are {df.ppm2_land[df.spec_electricity_va.notna()].median() / df.ppm2_land[df.spec_electricity_va.isna()].median() - 1:+.0%} dearer per m² "
                "(median), so a present value says something about the listing as well as the house.", plot["missing"]),
        section("Outliers", f"{len(flagged)} listings sit more than {OUTLIER_Z} robust standard deviations from their city's median price per m². "
                "Kept (removing them would bias the target), but reviewed in the error analysis.", table_html(flagged)),
        section("Noise floor", f"{int(noise.pairs.iloc[0])} listing pairs share district, land and building area and rooms. "
                f"{noise['share with equal price'].iloc[0]:.0%} have the same price (re-listings); the others differ by a median of "
                f"{noise['median gap, unequal prices'].iloc[0]:.0%}, which implies about {noise['implied median error, unequal prices'].iloc[0]:.0%} "
                "noise per listing: well below the model's error, so agent pricing noise is not the limit, missing information about the house is.",
                table_html(noise.round(3))),
        section("Location", f"{df.coord_is_centroid.mean():.0%} of listings sit at their district centroid, not their own location. "
                f"Building area is floor area summed over floors (median building/land ratio {ratio.get(1.0, np.nan):.2f} for 1 floor, "
                f"{ratio.get(2.0, np.nan):.2f} for 2).", plot["map"]),
        section("Spatial dependence", f"With the city median removed, Moran's I is {moran.moran_city_adjusted.iloc[0]:.2f} within 1 km and "
                f"{moran.moran_city_adjusted.iloc[-1]:.2f} at 10-20 km: spatial CV needs blocks of about 10 km or more.", plot["moran"]),
        section("Time", f"Listings created {df.created_at.min():%Y-%m} to {df.created_at.max():%Y-%m}; monthly deviations stay within "
                f"{by_month.resid.min():+.2f} to {by_month.resid.max():+.2f}, no clear trend.", plot["month"]),
        section("Cleaning rules", "Every rule is code (src/ingestion/validate.py, src/modeling/split.py); the test set was carved before this EDA.",
                table_html(steps)),
    ]
    tiles = [
        tile(f"{len(df):,}", "training listings (test set not used)"),
        tile(f"{df.ppm2_land.median() / 1e6:.1f} M", "median IDR per m² of land"),
        tile(f"{df.coord_is_centroid.mean():.0%}", "listings at a district centroid"),
        tile(f"{int((kecamatan >= 5).sum())} / {KECAMATAN_TOTAL}", "kecamatan with 5+ listings"),
        tile("~5 km", "range of price similarity"),
    ]
    subtitle = (f"Portal asking prices, listings created {df.created_at.min():%Y-%m} to {df.created_at.max():%Y-%m}; training part only. "
                "Generated by <code>uv run python -m src.analysis.eda</code>.")
    REPORT.write_text(page("Jabodetabek house prices: EDA", subtitle, tiles, sections), encoding="utf-8")
    print(f"wrote {REPORT} ({REPORT.stat().st_size / 1e6:.1f} MB), {len(figures)} PNGs")
    print(f"correlated pairs: {len(pairs)} | VIF >= 10: {len(high_vif)} | outliers: {len(flagged)}")
    print(pairs.round(2).to_string(index=False))
    print(vif.head(8).to_string(index=False))
    print(flags.round(3).to_string(index=False))
