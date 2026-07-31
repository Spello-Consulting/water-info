"""Server-rendered SVG line charts (no client-side charting dependency).

Produces a self-contained ``<svg>`` string styled via CSS classes (see
static/style.css) so it themes with the rest of the site. Horizontal reference
lines mark the high/low over the charting period, per design.md.
"""
from __future__ import annotations

import datetime as dt
from html import escape

from sc_foundation.sc_date_helper import DateHelper

_W = 820
_H = 380
_ML, _MR, _MT, _MB = 56, 20, 24, 40  # margins
_PLOT_W = _W - _ML - _MR
_PLOT_H = _H - _MT - _MB


def _nice_bounds(lo: float, hi: float, card_type: str) -> tuple[float, float]:
    if card_type == "water":
        return 0.0, 100.0
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * 0.1
    return lo - pad, hi + pad


def render_chart_svg(
    points: list[tuple[dt.datetime, float]],
    lo: float | None,
    hi: float | None,
    unit: str,
    card_type: str,
    days: int,
) -> str:
    """Render the chart. ``points`` are (timestamp, value) ordered by time."""
    if not points:
        return (
            f'<svg class="chart" viewBox="0 0 {_W} {_H}" role="img" '
            f'aria-label="No data available">'
            f'<text class="chart-empty" x="{_W / 2}" y="{_H / 2}" text-anchor="middle">'
            f"No data available yet</text></svg>"
        )

    values = [v for _, v in points]
    data_lo, data_hi = min(values), max(values)
    ref_lo = lo if lo is not None else data_lo
    ref_hi = hi if hi is not None else data_hi
    y_lo, y_hi = _nice_bounds(min(data_lo, ref_lo), max(data_hi, ref_hi), card_type)
    y_span = (y_hi - y_lo) or 1.0

    t0 = points[0][0].timestamp()
    t1 = points[-1][0].timestamp()
    t_span = (t1 - t0) or 1.0

    def sx(ts: dt.datetime) -> float:
        return _ML + (ts.timestamp() - t0) / t_span * _PLOT_W

    def sy(value: float) -> float:
        return _MT + (y_hi - value) / y_span * _PLOT_H

    parts: list[str] = [
        f'<svg class="chart" viewBox="0 0 {_W} {_H}" role="img" '
        f'aria-label="{escape(card_type)} chart, last {days} days">'
    ]

    # Y grid + labels (5 ticks)
    for i in range(5):
        val = y_lo + y_span * i / 4
        y = sy(val)
        label = f"{round(val):d}" if card_type == "water" else f"{val:.1f}"
        parts.append(f'<line class="chart-grid" x1="{_ML}" y1="{y:.1f}" x2="{_W - _MR}" y2="{y:.1f}"/>')
        parts.append(f'<text class="chart-axis" x="{_ML - 8}" y="{y + 4:.1f}" text-anchor="end">{label}{escape(unit)}</text>')

    # X labels (up to 6 date ticks)
    n_ticks = min(6, len(points))
    for i in range(n_ticks):
        idx = round(i * (len(points) - 1) / max(n_ticks - 1, 1))
        ts = points[idx][0]
        x = sx(ts)
        parts.append(f'<text class="chart-axis" x="{x:.1f}" y="{_H - _MB + 20}" text-anchor="middle">{escape(DateHelper.format(ts, "%d %b"))}</text>')

    # High/low reference lines
    for ref, name in ((ref_hi, "high"), (ref_lo, "low")):
        y = sy(ref)
        label = f"{round(ref):d}" if card_type == "water" else f"{ref:.1f}"
        parts.append(f'<line class="chart-ref chart-ref-{name}" x1="{_ML}" y1="{y:.1f}" x2="{_W - _MR}" y2="{y:.1f}"/>')
        parts.append(f'<text class="chart-ref-label" x="{_W - _MR - 4}" y="{y - 4:.1f}" text-anchor="end">{name} {label}{escape(unit)}</text>')

    # Data line
    d = " ".join(f"{'M' if i == 0 else 'L'}{sx(ts):.1f} {sy(v):.1f}" for i, (ts, v) in enumerate(points))
    parts.append(f'<path class="chart-line" d="{d}"/>')

    parts.append("</svg>")
    return "".join(parts)
