from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import numpy as np
import matplotlib.pyplot as plt


def plot_temp_pressure(rows, out_prefix: str = "tpms", show: bool = False):
    """
    rows: iterable of (datetime, id_str, temp_C|None, pressure_PSI|None)

    Produces:
      - {out_prefix}_temp.png
      - {out_prefix}_pressure.png

    Returns (temp_path, pressure_path) if not show, else (None, None).
    """
    by_id = defaultdict(lambda: {"t": [], "temp": [], "pres": []})

    for t, sid, temp_c, pres_psi in rows:
        d = by_id[str(sid)]
        d["t"].append(t)
        d["temp"].append(temp_c)
        d["pres"].append(pres_psi)

    if not by_id:
        raise ValueError("No rows to plot")

    # --- Temperature plot ---
    fig1, ax1 = plt.subplots(figsize=(12, 6))
    any_temp = False

    for sid, d in sorted(by_id.items()):
        if any(v is not None for v in d["temp"]):
            tt = [d["t"][i] for i, v in enumerate(d["temp"]) if v is not None]
            vv = [v for v in d["temp"] if v is not None]
            ax1.plot(tt, vv, label=str(sid))
            any_temp = True

    ax1.set_xlabel("Time")
    ax1.set_ylabel("Temperature (°C)")
    ax1.set_title("Temperature by sensor ID")
    if any_temp:
        ax1.legend(loc="best")
    fig1.autofmt_xdate()
    plt.tight_layout()

    # --- Pressure plot ---
    fig2, ax2 = plt.subplots(figsize=(12, 6))
    any_pres = False

    for sid, d in sorted(by_id.items()):
        if any(v is not None for v in d["pres"]):
            tt = [d["t"][i] for i, v in enumerate(d["pres"]) if v is not None]
            vv = [v for v in d["pres"] if v is not None]
            ax2.plot(tt, vv, label=str(sid))
            any_pres = True

    ax2.set_xlabel("Time")
    ax2.set_ylabel("Pressure (PSI)")
    ax2.set_title("Pressure by sensor ID")
    if any_pres:
        ax2.legend(loc="best")
    fig2.autofmt_xdate()
    plt.tight_layout()

    if show:
        plt.show()
        return (None, None)

    temp_path = f"{out_prefix}_temp.png"
    pres_path = f"{out_prefix}_pressure.png"
    fig1.savefig(temp_path, dpi=200)
    fig2.savefig(pres_path, dpi=200)
    plt.close(fig1)
    plt.close(fig2)
    return (temp_path, pres_path)


def plot_home_raster(
    home_intervals,
    bin_minutes: int = 5,
    out: str = "home_raster.png",
    show: bool = False,
):
    """
    home_intervals: list[(start_dt, end_dt)] with naive or timezone-consistent datetimes
    Produces a raster: X=day, Y=time-of-day, black=home.
    Saves to `out`.
    """
    if not home_intervals:
        raise ValueError("home_intervals is empty")

    # Day range (inclusive)
    start_day = min(a.date() for a, _ in home_intervals)
    end_day = max(b.date() for _, b in home_intervals)

    days = []
    d = start_day
    while d <= end_day:
        days.append(d)
        d += timedelta(days=1)

    day_to_x = {d: i for i, d in enumerate(days)}
    bins_per_day = (24 * 60) // bin_minutes
    # Base grid: rows=time bins, cols=days
    grid = np.zeros((bins_per_day, len(days)), dtype=np.uint8)

    for a, b in home_intervals:
        if b <= a:
            continue

        # Walk day by day to handle intervals spanning midnight
        day = a.date()
        while day <= b.date():
            x = day_to_x.get(day)
            if x is None:
                day = day + timedelta(days=1)
                continue

            day_start = datetime.combine(day, datetime.min.time())
            day_end = day_start + timedelta(days=1)

            seg_start = max(a, day_start)
            seg_end = min(b, day_end)

            if seg_end > seg_start:
                s_min = int((seg_start - day_start).total_seconds() // 60)
                e_min = int((seg_end - day_start).total_seconds() // 60)

                s_bin = s_min // bin_minutes
                e_bin = (e_min + bin_minutes - 1) // bin_minutes  # ceil

                s_bin = max(0, min(bins_per_day, s_bin))
                e_bin = max(0, min(bins_per_day, e_bin))
                if e_bin > s_bin:
                    grid[s_bin:e_bin, x] = 1

            day = day + timedelta(days=1)

    # ---- Add thin white separators between days ----
    # day columns go at 0,2,4,... and separator columns (all zeros/white) at 1,3,5,...
    n_days = len(days)
    n_cols = 2 * n_days - 1
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
    else:
        plt.savefig(out, dpi=250)
        plt.close(fig)
        return out

    return out
