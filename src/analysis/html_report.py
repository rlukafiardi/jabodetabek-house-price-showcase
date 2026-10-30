"""Shared building blocks for the HTML reports: dataviz palette, chart style, summary tiles, sections, page template."""

import html
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.io import to_html

# dataviz reference palette (light): text ink, surface, grid, single-series blue, diverging red / neutral / blue
INK, MUTED, SURFACE, GRID = "#0b0b0b", "#52514e", "#fcfcfb", "#e8e7e3"
BLUE, RED, NEUTRAL, GREY = "#2a78d6", "#e34948", "#f0efec", "#b9b8b2"
BLUES = [[0, "#cde2fb"], [0.5, "#3987e5"], [1, "#0d366b"]]
DIVERGING = [[0, RED], [0.5, NEUTRAL], [1, BLUE]]


def styled(fig: go.Figure, title: str, height: int = 380, legend: bool = False) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, x=0, y=0.98, yanchor="top", font=dict(size=15, color=INK)), height=height,
        margin=dict(l=10, r=10, t=90 if legend else 56, b=40), paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, showlegend=legend,
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", size=12, color=MUTED),
        hoverlabel=dict(bgcolor="white", font_color=INK), legend=dict(orientation="h", x=0, y=1.0, yanchor="bottom"),  # between title and plot
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    return fig


def table_html(df: pd.DataFrame) -> str:
    return df.to_html(index=False, border=0, classes="tbl", float_format=lambda v: f"{v:,.2f}")


def tile(value: str, label: str) -> str:
    return f'<div class="tile"><div class="v">{html.escape(value)}</div><div class="l">{html.escape(label)}</div></div>'


def section(title: str, takeaway: str, body: str) -> str:
    return f'<section><h2>{html.escape(title)}</h2><p class="take">{html.escape(takeaway)}</p>{body}</section>'


def plots_html(figures: dict[str, go.Figure]) -> dict[str, str]:
    """Each figure as an HTML fragment; plotly.js is embedded once, with the first figure, so the page works offline."""
    return {name: to_html(fig, full_html=False, include_plotlyjs=(i == 0), config={"displayModeBar": False, "responsive": True})
            for i, (name, fig) in enumerate(figures.items())}


def save_pngs(figures: dict[str, go.Figure], folder: Path, prefix: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, fig in figures.items():
        fig.write_image(folder / f"{prefix}_{name}.png", width=1000, height=fig.layout.height, scale=2)


def page(title: str, subtitle: str, tiles: list[str], sections: list[str]) -> str:
    """subtitle may contain HTML (e.g. <code>); everything else is escaped by the helpers above."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root {{ color-scheme: light; }}
body {{ margin: 0; background: {SURFACE}; color: {INK}; font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px 64px; }}
h1 {{ font-size: 26px; margin: 0 0 4px; }}
.sub {{ color: {MUTED}; margin: 0 0 20px; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-bottom: 8px; }}
.tile {{ background: #fff; border: 1px solid {GRID}; border-radius: 10px; padding: 14px 16px; }}
.tile .v {{ font-size: 24px; font-weight: 600; }}
.tile .l {{ color: {MUTED}; font-size: 13px; }}
section {{ background: #fff; border: 1px solid {GRID}; border-radius: 10px; padding: 16px; margin-top: 16px; overflow-x: auto; }}
h2 {{ font-size: 18px; margin: 0 0 4px; }}
.take {{ color: {MUTED}; margin: 0 0 8px; }}
.tbl {{ border-collapse: collapse; margin: 8px 24px 0 0; font-size: 13px; display: inline-table; vertical-align: top; }}
.tbl th, .tbl td {{ text-align: left; padding: 4px 12px 4px 0; border-bottom: 1px solid {GRID}; }}
</style></head>
<body><main>
<h1>{html.escape(title)}</h1>
<p class="sub">{subtitle}</p>
<div class="tiles">{"".join(tiles)}</div>
{"".join(sections)}
</main></body></html>
"""
