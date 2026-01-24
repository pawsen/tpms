#!/usr/bin/env python3
import argparse
import glob
import gzip
import json
from collections import defaultdict
from datetime import date, datetime, time as dtime, timedelta


from plots import plot_home_raster, plot_series

# Defaults if no --sensor and no --id are provided.
# Prefer DEFAULT_SENSORS to avoid ID collisions across models.
DEFAULT_SENSORS = [
    ("Toyota", "d9bd4f7c"),
    ("Toyota", "d9b796c4"),
]
DEFAULT_IDS: list[str] = []


def parse_sensor_specs(specs: list[str]) -> set[tuple[str, str]]:
    """
    Parse repeated --sensor MODEL:ID into a set of (model, id_str).
    """
    out: set[tuple[str, str]] = set()
    for s in specs:
        if ":" not in s:
            raise SystemExit(f"Bad --sensor '{s}'. Expected MODEL:ID")
        model, sid = s.split(":", 1)
        model = model.strip()
        sid = sid.strip()
        if not model or not sid:
            raise SystemExit(f"Bad --sensor '{s}'. Expected MODEL:ID")
        out.add((model, sid))
    return out


def parse_lines(
    logfile: str,
    start: date | None = None,
    end: date | None = None,
    allowed_ids: set[str] | None = None,
    allowed_sensors: set[tuple[str, str]] | None = None,  # {(model, id_str)}
    extra_fields: list[str] | None = None,
):
    """
    Read JSONL/JSONL.GZ from a single file path OR a glob.

    Filtering priority:
      - if allowed_sensors is set: require (model, id) match
      - else if allowed_ids is set: require id match
      - else: no filtering

    Returns sorted rows:
      (t: datetime, model: str|None, id_str: str, fields: dict)
    fields always includes:
      - temp_c (float|None)
      - pressure_psi (float|None)
    extras: any keys listed in extra_fields, if present in the JSON.
    """
    start_dt = datetime.combine(start, dtime.min) if start else None
    end_dt = datetime.combine(end, dtime.max) if end else None

    paths = glob.glob(logfile)
    if not paths:
        raise FileNotFoundError(f"No files match: {logfile}")
    paths.sort()

    extra_fields = extra_fields or []

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

                model = obj.get("model")
                model_s = str(model) if model is not None else None

                # Apply filtering
                if allowed_sensors is not None:
                    if model_s is None or (model_s, sid_s) not in allowed_sensors:
                        continue
                elif allowed_ids is not None:
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

                # Temperature: prefer C; if only F exists, convert to C
                temp_c = obj.get("temperature_C")
                if temp_c is not None:
                    try:
                        temp_c = float(temp_c)
                    except Exception:
                        temp_c = None
                else:
                    temp_f = obj.get("temperature_F")
                    if temp_f is not None:
                        try:
                            temp_c = (float(temp_f) - 32.0) * (5.0 / 9.0)
                        except Exception:
                            temp_c = None
                    else:
                        temp_c = None

                pressure = obj.get("pressure_PSI")
                if pressure is not None:
                    try:
                        pressure = float(pressure)
                    except Exception:
                        pressure = None
                else:
                    pressure = None

                fields = {
                    "temp_c": temp_c,
                    "pressure_psi": pressure,
                }

                # Optional extras (humidity should live here)
                for k in extra_fields:
                    if k in obj:
                        v = obj.get(k)
                        if isinstance(v, (int, float)):
                            fields[k] = v
                        else:
                            try:
                                fields[k] = float(v)
                            except Exception:
                                fields[k] = v

                rows.append((t, model_s, sid_s, fields))

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
      - HOME ends at last_seen (actual evidence), not last_seen+window
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

    if in_home and first_seen is not None and last_seen is not None:
        intervals.append((first_seen, last_seen))

    return intervals


def main():
    ap = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Single file (positional):\n"
            "  python tpms.py cleaned.jsonl --sensor Toyota:d9bd4f7c --sensor Toyota:d9b796c4 --window-minutes 20 --show\n"
            "\n"
            "  # Disambiguate same ID across models:\n"
            "  python tpms.py tpms_current.jsonl --sensor Bresser-3CH:251 --window-minutes 40 --show\n"
            "  python tpms.py tpms_current.jsonl --sensor Nexus-TH:251 --window-minutes 40 --show\n"
            "\n"
            "  # Read rotated gz logs for a date range (inclusive):\n"
            "  python tpms.py '/var/log/rtl_433/tpms/tpms_current.jsonl-2026-01-*.gz' \\\n"
            "    --start 2026-01-21 --end 2026-01-26 \\\n"
            "    --sensor Bresser-3CH:251 --window-minutes 40 --show\n"
            "\n"
            "Notes:\n"
            "  - Quote globs so the shell does not expand them.\n"
            "  - --start/--end filter on the JSON field 'time' (not filename).\n"
        ),
        description="Presence + plots from rtl_433 JSONL logs.",
    )

    # Optional positional logfile (so: python tpms.py cleaned.jsonl ...)
    ap.add_argument(
        "logfile_pos",
        nargs="?",
        default=None,
        help="Input file or glob (same as --logfile)",
    )
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
        "--sensor",
        action="append",
        default=None,
        help="Filter by MODEL:ID (repeat). Example: --sensor Toyota:d9bd4f7c or --sensor Bresser-3CH:251",
    )
    ap.add_argument(
        "--id",
        dest="ids",
        action="append",
        default=None,
        help="Filter by ID only (repeat). Use --sensor to disambiguate same ID across models.",
    )
    ap.add_argument(
        "--field",
        action="append",
        default=[],
        help="Extra field to capture if present (repeat). Example: --field humidity --field channel",
    )
    ap.add_argument(
        "--window-minutes",
        type=int,
        default=10,
        help="Gap window to bridge packets into one HOME interval",
    )
    ap.add_argument(
        "--bin-seconds",
        type=int,
        default=60,
        help="Time binning resolution for home detection (seconds)",
    )
    ap.add_argument(
        "--bin-minutes", type=int, default=5, help="Plot Y resolution (minutes)"
    )
    ap.add_argument(
        "--show", action="store_true", help="Interactive plot (local testing)"
    )
    ap.add_argument(
        "--out-prefix",
        default="tpms",
        help="Output prefix for plots (default: tpms)",
    )

    args = ap.parse_args()
    logfile = args.logfile_pos or args.logfile or "cleaned.jsonl"

    # Choose filtering mode (sensor > id > defaults)
    allowed_sensors = parse_sensor_specs(args.sensor) if args.sensor else None
    allowed_ids = None

    if allowed_sensors is None:
        allowed_ids = (
            set(args.ids) if args.ids else (set(DEFAULT_IDS) if DEFAULT_IDS else None)
        )

    if allowed_sensors is None and allowed_ids is None:
        allowed_sensors = set(DEFAULT_SENSORS)

    if allowed_sensors is not None:
        print(f"Using sensors={sorted(allowed_sensors)}")
    else:
        print(f"Using ids={sorted(allowed_ids)}")

    # Default extras: none. Humidity is optional; add via --field humidity
    extra_fields = list(dict.fromkeys(args.field))  # preserve order, unique

    rows = parse_lines(
        logfile,
        start=args.start,
        end=args.end,
        allowed_ids=allowed_ids,
        allowed_sensors=allowed_sensors,
        extra_fields=extra_fields,
    )

    times = [t for (t, _, _, _) in rows]
    print(f"Packets after filter: {len(times)}")

    home_intervals = detect_home_intervals(
        times,
        bin_seconds=args.bin_seconds,
        window_minutes=args.window_minutes,
    )

    if not home_intervals:
        print(
            "No HOME intervals detected (try increasing --window-minutes or check filters)."
        )
        return

    for a, b in home_intervals[:10]:
        print(a, "->", b, (b - a))

    res1 = plot_home_raster(
        home_intervals,
        bin_minutes=args.bin_minutes,
        out_prefix=args.out_prefix,
        show=args.show,
    )
    if not args.show and res1:
        print("Wrote", res1)

    for fld in ["temp_c", "pressure_psi"] + args.field:
        outp = plot_series(rows, field=fld, out_prefix=args.out_prefix, show=args.show)
        if not args.show:
            if outp:
                print("Wrote", outp)
            else:
                print(f"Skipping {fld} (no data)")


if __name__ == "__main__":
    main()
