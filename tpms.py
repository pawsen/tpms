import argparse
import json
from datetime import datetime, timedelta, date, time as dtime
from collections import defaultdict
import glob
import gzip

from plots import plot_home_raster, plot_temp_pressure

# Default IDs if none provided on CLI (use strings to handle int IDs too)
DEFAULT_IDS = [
    "d9bd4f7c",
    "d9b796c4",
    # "251",
]


def parse_lines(
    logfile: str,
    allowed_ids: set[str],
    start: date | None = None,
    end: date | None = None,
):
    """
    Read JSONL/JSONL.GZ from a single file path OR a glob.
    Keeps only records whose 'id' is in allowed_ids.
    Filters by [start, end] inclusive on obj["time"] if provided.

    Returns sorted rows:
      (t: datetime, id_str: str, temp_c: float|None, pressure_psi: float|None)
    """
    start_dt = datetime.combine(start, dtime.min) if start else None
    end_dt = datetime.combine(end, dtime.max) if end else None

    paths = glob.glob(logfile)
    if not paths:
        raise FileNotFoundError(f"No files match: {logfile}")
    paths.sort()

    rows = []
    for p in paths:
        opener = gzip.open if p.endswith(".gz") else open
        with opener(p, "rt", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue  # drop non-JSON lines

                sid = obj.get("id")
                if sid is None:
                    continue
                sid_s = str(sid)
                if sid_s not in allowed_ids:
                    continue

                try:
                    t = datetime.fromisoformat(obj["time"])
                except Exception:
                    continue

                if start_dt and t < start_dt:
                    continue
                if end_dt and t > end_dt:
                    continue

                temp_c = obj.get("temperature_C")
                temp_c = float(temp_c) if temp_c is not None else None

                pressure = obj.get("pressure_PSI")
                pressure = float(pressure) if pressure is not None else None

                rows.append((t, sid_s, temp_c, pressure))

    rows.sort(key=lambda x: x[0])
    return rows


def detect_home_intervals(
    times: list[datetime],
    bin_seconds: int = 60,
    window_minutes: int = 10,
) -> list[tuple[datetime, datetime]]:
    """
    Gap-bridging presence:
      - Bin events into bin_seconds buckets
      - HOME starts at first seen bin
      - HOME continues as long as another event occurs within window_minutes
      - HOME ends at last_seen
    """
    if not times:
        return []

    start = times[0].replace(second=0, microsecond=0)
    end = times[-1].replace(second=0, microsecond=0) + timedelta(minutes=1)

    evidence = defaultdict(int)
    for t in times:
        tbin = t.replace(second=0, microsecond=0)
        evidence[tbin] += 1

    window = timedelta(minutes=window_minutes)
    intervals: list[tuple[datetime, datetime]] = []
    in_home = False
    first_seen = None
    last_seen = None

    t = start
    while t < end:
        seen = evidence[t] > 0

        if seen:
            if not in_home:
                in_home = True
                first_seen = t
            last_seen = t

        # close interval when gap exceeds window
        if in_home and last_seen is not None and (t - last_seen) > window:
            intervals.append((first_seen, last_seen))
            in_home = False
            first_seen = None
            last_seen = None

        t += timedelta(seconds=bin_seconds)

    # close if still open
    if in_home and first_seen is not None and last_seen is not None:
        intervals.append((first_seen, last_seen))

    return intervals


def main():
    ap = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        description=(
            "TPMS presence plotting from rtl_433 JSONL logs.\n"
            "\n"
            "Examples:\n"
            "  # Single file (positional):\n"
            "  python tpms.py cleaned.jsonl --id d9bd4f7c --id d9b796c4 --window-minutes 20 --show\n"
            "\n"
            "  # Same, using --logfile:\n"
            "  python tpms.py --logfile cleaned.jsonl --id 251 --window-minutes 40 --show\n"
            "\n"
            "  # Read rotated gz logs for a date range (inclusive):\n"
            "  python tpms.py '/var/log/rtl_433/tpms/tpms_current.jsonl-2026-01-*.gz' \\\n"
            "    --start 2026-01-21 --end 2026-01-26 \\\n"
            "    --id 251 --window-minutes 40 --show\n"
            "\n"
            "Notes:\n"
            "  - Quote globs so the shell does not expand them.\n"
            "  - --start/--end filter on the JSON field 'time' (not filename).\n"
        ),
    )

    # Optional positional logfile (so: python tpms.py cleaned.jsonl ...)
    ap.add_argument(
        "logfile_pos",
        nargs="?",
        default=None,
        help="Input file or glob (same as --logfile)",
    )

    # Optional flag form (so: python tpms.py --logfile cleaned.jsonl ...)
    ap.add_argument(
        "--logfile",
        default=None,
        help="Input file or glob. Examples: ./cleaned.jsonl, ./cleaned.jsonl.gz, "
        "/var/log/rtl_433/tpms/tpms_current.jsonl*",
    )

    ap.add_argument(
        "--start",
        type=date.fromisoformat,
        default=None,
        help="Start date inclusive, e.g. 2026-01-21",
    )
    ap.add_argument(
        "--end",
        type=date.fromisoformat,
        default=None,
        help="End date inclusive, e.g. 2026-01-24",
    )
    ap.add_argument(
        "--id",
        dest="ids",
        action="append",
        default=None,
        help="Include only this id (repeat --id ...). If omitted, uses DEFAULT_IDS in script.",
    )

    ap.add_argument(
        "--window-minutes",
        type=int,
        default=10,
        help="HOME persists this long after last packet",
    )
    ap.add_argument(
        "--bin-seconds", type=int, default=60, help="Time binning resolution (seconds)"
    )

    ap.add_argument(
        "--bin-minutes", type=int, default=5, help="Plot Y resolution (minutes)"
    )
    ap.add_argument("--out", default="home_raster.png")
    ap.add_argument(
        "--show", action="store_true", help="Interactive plot (local testing)"
    )

    args = ap.parse_args()
    logfile = args.logfile_pos or args.logfile or "cleaned.jsonl"

    allowed_ids = set(args.ids) if args.ids else set(DEFAULT_IDS)
    print(f"Using ids={sorted(allowed_ids)}")

    rows = parse_lines(logfile, allowed_ids=allowed_ids, start=args.start, end=args.end)
    times = [t for (t, _, _, _) in rows]
    print(f"Packets after id-filter: {len(times)}")

    home_intervals = detect_home_intervals(
        times,
        bin_seconds=args.bin_seconds,
        window_minutes=args.window_minutes,
    )

    if not home_intervals:
        print(
            "No HOME intervals detected (try increasing --window-minutes or check IDs)."
        )
        return

    for a, b in home_intervals[:10]:
        print(a, "->", b, (b - a))

    res1 = plot_home_raster(
        home_intervals, bin_minutes=args.bin_minutes, out=args.out, show=args.show
    )
    if not args.show:
        print("Wrote", res1)

    tpath, ppath = plot_temp_pressure(rows, out_prefix="tpms", show=args.show)
    if not args.show:
        print("Wrote", tpath)
        print("Wrote", ppath)


if __name__ == "__main__":
    main()
