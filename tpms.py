import argparse
import json
from datetime import datetime, timedelta
from collections import defaultdict

from plots import plot_home_raster

# Defaults if no --id is provided (strings on purpose)
DEFAULT_IDS = [
    # "d9bd4f7c",
    # "d9b796c4",
    "251",  # Bresser/Nexus example (numeric id in data)
]


def parse_lines(path, allowed_ids=None):
    """
    Returns rows: (time: datetime, id_str: str, rssi: float|None)
    allowed_ids: set[str] or None
    """
    rows = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            obj = json.loads(line)

            sid = obj.get("id")
            if sid is None:
                continue
            sid_s = str(sid)

            if allowed_ids is not None and sid_s not in allowed_ids:
                continue

            t = datetime.fromisoformat(obj["time"])

            rssi = obj.get("rssi", None)
            rssi = float(rssi) if rssi is not None else None

            rows.append((t, sid_s, rssi))

    rows.sort(key=lambda x: x[0])
    return rows


def _near_from_bin(e, rssi_gate, use_rssi):
    """
    e: dict with keys max_rssi, count
    """
    if not use_rssi:
        return e["count"] >= 1
    has_rssi = e["max_rssi"] != float("-inf")
    return (e["max_rssi"] >= rssi_gate) if has_rssi else (e["count"] >= 1)


def detect_home_intervals(
    rows,
    bin_seconds=60,
    rssi_gate=-12.0,
    tau_minutes=30.0,
    enter_score=0.7,
    exit_score=0.3,
    enter_hold_minutes=5,
    exit_hold_minutes=20,
    use_score=True,
    use_rssi=True,
):
    """
    If use_score=True:
      - exponential decay presence score + hysteresis (enter/exit holds)
    If use_score=False:
      - "home" iff packets present in that bin (or RSSI-gated if use_rssi=True)
        (i.e., no decay/hysteresis; purely presence-based)
    """
    if not rows:
        return []

    start = rows[0][0].replace(second=0, microsecond=0)
    end = rows[-1][0].replace(second=0, microsecond=0) + timedelta(minutes=1)

    evidence = defaultdict(
        lambda: {"max_rssi": float("-inf"), "count": 0, "ids": set()}
    )

    for t, sid, rssi in rows:
        tbin = t.replace(second=0, microsecond=0)
        e = evidence[tbin]
        e["count"] += 1
        e["ids"].add(sid)
        if rssi is not None:
            e["max_rssi"] = max(e["max_rssi"], rssi)

    # ---- Mode A: simple presence (no score) ----
    if not use_score:
        intervals = []
        in_home = False
        current_start = None

        t = start
        while t < end:
            e = evidence[t]
            near = _near_from_bin(e, rssi_gate, use_rssi)

            if near and not in_home:
                in_home = True
                current_start = t
            elif (not near) and in_home:
                in_home = False
                intervals.append((current_start, t))
                current_start = None

            t += timedelta(seconds=bin_seconds)

        if in_home and current_start is not None:
            intervals.append((current_start, end))

        return intervals

    # ---- Mode B: score-based presence ----
    tau = tau_minutes * 60.0
    dt = bin_seconds
    decay = pow(2.718281828, -dt / tau)

    S = 0.0
    state = "AWAY"
    enter_ok = 0
    exit_ok = 0

    intervals = []
    current_start = None

    t = start
    while t < end:
        e = evidence[t]
        near = _near_from_bin(e, rssi_gate, use_rssi)

        S *= decay
        if near:
            S = min(1.0, S + 0.2)

        if state == "AWAY":
            if S >= enter_score:
                enter_ok += 1
                if enter_ok >= enter_hold_minutes:
                    state = "HOME"
                    current_start = t - timedelta(minutes=enter_hold_minutes - 1)
                    enter_ok = 0
            else:
                enter_ok = 0
        else:  # HOME
            if S <= exit_score:
                exit_ok += 1
                if exit_ok >= exit_hold_minutes:
                    state = "AWAY"
                    interval_end = t - timedelta(minutes=exit_hold_minutes - 1)
                    intervals.append((current_start, interval_end))
                    current_start = None
                    exit_ok = 0
            else:
                exit_ok = 0

        t += timedelta(seconds=bin_seconds)

    if state == "HOME" and current_start is not None:
        intervals.append((current_start, end))

    return intervals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="cleaned.jsonl", help="Input JSONL file")

    ap.add_argument(
        "--id",
        dest="ids",
        action="append",
        default=None,
        help="Include only this id (repeat --id ...). If omitted, uses DEFAULT_IDS in script.",
    )

    ap.add_argument(
        "--no-score",
        dest="use_score",
        action="store_false",
        help="Disable presence score; home only when packets exist in the bin.",
    )
    ap.set_defaults(use_score=True)

    ap.add_argument(
        "--no-rssi",
        dest="use_rssi",
        action="store_false",
        help="Disable RSSI usage; near = count>=1.",
    )
    ap.set_defaults(use_rssi=True)

    ap.add_argument("--rssi-gate", type=float, default=-12.0)
    ap.add_argument("--bin-seconds", type=int, default=60)

    # Score parameters (only relevant if use_score=True)
    ap.add_argument("--tau-minutes", type=float, default=30.0)
    ap.add_argument("--enter-score", type=float, default=0.7)
    ap.add_argument("--exit-score", type=float, default=0.3)
    ap.add_argument("--enter-hold-minutes", type=int, default=5)
    ap.add_argument("--exit-hold-minutes", type=int, default=20)

    # Plot controls
    ap.add_argument("--bin-minutes", type=int, default=5, help="Plot Y resolution")
    ap.add_argument("--out", default="home_raster.png")
    ap.add_argument(
        "--show", action="store_true", help="Interactive plot (local testing)"
    )

    args = ap.parse_args()

    allowed_ids = set(args.ids) if args.ids else set(DEFAULT_IDS)

    rows = parse_lines(args.path, allowed_ids=allowed_ids)
    print(f"Rows after id-filter: {len(rows)} (ids={sorted(allowed_ids)})")

    home_intervals = detect_home_intervals(
        rows,
        bin_seconds=args.bin_seconds,
        rssi_gate=args.rssi_gate,
        tau_minutes=args.tau_minutes,
        enter_score=args.enter_score,
        exit_score=args.exit_score,
        enter_hold_minutes=args.enter_hold_minutes,
        exit_hold_minutes=args.exit_hold_minutes,
        use_score=args.use_score,
        use_rssi=args.use_rssi,
    )
    if not home_intervals:
        print(
            "No HOME intervals detected (try --no-score and/or --no-rssi, or adjust thresholds)."
        )
        return
    for a, b in home_intervals[:10]:
        print(a, "->", b, (b - a))

    res = plot_home_raster(
        home_intervals,
        bin_minutes=args.bin_minutes,
        out=args.out,
        show=args.show,
    )
    if res:
        print("Wrote", res)


if __name__ == "__main__":
    main()
