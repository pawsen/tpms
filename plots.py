# plots.py
from __future__ import annotations

from collections import defaultdict
import re
from datetime import datetime, timedelta, time as dtime

import matplotlib.pyplot as plt
import numpy as np


# Minimal label map with sane units. Anything not listed falls back to the field name.
YLABEL = {
    "temp_c": "Temperature (°C)",
    "pressure_psi": "Pressure (PSI)",
    "humidity": "Humidity (%)",
}


def _safe_name(s: str) -> str:
    s = s.strip()
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    return s or "field"


def plot_home_raster(
    home_intervals: list[tuple[datetime, datetime]],
    bin_minutes: int = 5,
    out_prefix: str = "tmps",
    show: bool = False,
):
    """
    Plot presence as a day (x) vs time-of-day (y) raster.

    Uses separator columns to create thin white gaps between days:
      - day columns at 0,2,4,...
      - separator columns at 1,3,5,... (all zeros -> white)

    home_intervals: list of (start_datetime, end_datetime) with end = last_seen.
    """
    if not home_intervals:
        raise ValueError("home_intervals is empty")

    # Normalize/clip
    intervals = []
    for a, b in home_intervals:
        a = a.replace(second=0, microsecond=0)
        b = b.replace(second=0, microsecond=0)
        if b >= a:
            intervals.append((a, b))
    if not intervals:
        raise ValueError("home_intervals is empty after normalization")

    start_dt = min(a for a, _ in intervals)
    end_dt = max(b for _, b in intervals)

    first_day = start_dt.date()
    last_day = end_dt.date()
    days = [
        first_day + timedelta(days=i) for i in range((last_day - first_day).days + 1)
    ]
    n_days = len(days)

    bins_per_day = int((24 * 60) / bin_minutes)

    # grid: shape (bins_per_day, n_days), 1=home (black), 0=away (white)
    grid = np.zeros((bins_per_day, n_days), dtype=np.uint8)

    def clamp(v: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, v))

    for a, b in intervals:
        day = a.date()
        while day <= b.date():
            day_idx = (day - first_day).days
            day_start = datetime.combine(day, dtime.min)
            day_end = day_start + timedelta(days=1)

            seg_start = max(a, day_start)
            seg_end = min(b, day_end)

            start_min = int((seg_start - day_start).total_seconds() // 60)
            end_min = int((seg_end - day_start).total_seconds() // 60)

            start_bin = clamp(start_min // bin_minutes, 0, bins_per_day - 1)
            end_bin = clamp(end_min // bin_minutes, 0, bins_per_day - 1)

            grid[start_bin : end_bin + 1, day_idx] = 1
            day = day + timedelta(days=1)

    # ---- Add thin white separators between days ----
    # day columns go at 0,2,4,... and separator columns (all zeros/white) at 1,3,5,...
    n_cols = 2 * n_days - 1 if n_days > 0 else 0
    grid_sep = np.zeros((bins_per_day, n_cols), dtype=np.uint8)
    grid_sep[:, 0::2] = grid  # copy day data into even columns

    # Plot
    fig_w = max(10, n_days * 0.18)
    fig, ax = plt.subplots(figsize=(fig_w, 8))

    ax.imshow(
        grid_sep,
        aspect="auto",
        origin="lower",
        interpolation="nearest",
        cmap="Greys",
        vmin=0,
        vmax=1,
    )

    # X ticks on day columns only
    step = max(1, n_days // 10)
    day_indices = list(range(0, n_days, step))
    xticks = [2 * i for i in day_indices]
    ax.set_xticks(xticks)
    ax.set_xticklabels(
        [days[i].isoformat() for i in day_indices], rotation=45, ha="right"
    )

    # Y ticks: every 2 hours
    hour_step = 2
    yticks = [(h * 60) // bin_minutes for h in range(0, 24, hour_step)]
    ax.set_yticks(yticks)
    ax.set_yticklabels([f"{h:02d}:00" for h in range(0, 24, hour_step)])

    ax.set_xlabel("Day")
    ax.set_ylabel("Time of day")
    ax.set_title("Car home (black)")

    plt.tight_layout()

    if show:
        plt.show()
        return None

    out = f"{out_prefix}_seen.png"
    plt.savefig(out, dpi=250)
    plt.close(fig)
    return out


def plot_series(rows, field: str, out_prefix: str = "tpms", show: bool = False):
    """
    Generic "field vs time" plot.

    rows: iterable of (datetime, model, id_str, fields_dict)
    Plots fields_dict[field] vs time for each sensor (model:id in legend).
    Returns output path or None if nothing to plot (all values missing).
    """
    by_key = defaultdict(lambda: {"t": [], "v": []})

    for t, model, sid, fields in rows:
        key = f"{model}:{sid}" if model else sid
        v = fields.get(field)
        by_key[key]["t"].append(t)
        by_key[key]["v"].append(v)

    any_data = any(any(v is not None for v in d["v"]) for d in by_key.values())
    if not any_data:
        return None

    fig, ax = plt.subplots(figsize=(12, 6))

    for key, d in sorted(by_key.items()):
        if any(v is not None for v in d["v"]):
            tt = [d["t"][i] for i, v in enumerate(d["v"]) if v is not None]
            vv = [v for v in d["v"] if v is not None]
            ax.plot(tt, vv, label=key)

    ylabel = YLABEL.get(field, field)

    ax.set_xlabel("Time")
    ax.set_ylabel(ylabel)
    ax.set_title(f"{ylabel} by sensor")
    ax.legend(loc="best")

    fig.autofmt_xdate()
    plt.tight_layout()

    if show:
        plt.show()
        return None

    out = f"{out_prefix}_{_safe_name(field)}.png"
    fig.savefig(out, dpi=200)
    plt.close(fig)
    return out
