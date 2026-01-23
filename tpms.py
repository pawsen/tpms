import argparse
import json
from datetime import datetime, timedelta
from collections import defaultdict

from plots import plot_home_raster

# Default IDs if none provided on CLI (use strings to handle int IDs too)
DEFAULT_IDS = [
    "d9bd4f7c",
    "d9b796c4",
    # "251",
]


def parse_lines(path: str, allowed_ids: set[str]) -> list[datetime]:
    """
    Read JSONL, keep only records whose 'id' is in allowed_ids.
    Returns a sorted list of datetimes for matching packets.
    """
    times: list[datetime] = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)

            sid = obj.get("id")
            if sid is None:
                continue
            if str(sid) not in allowed_ids:
                continue

            times.append(datetime.fromisoformat(obj["time"]))

    times.sort()
    return times


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

    allowed_ids = set(args.ids) if args.ids else set(DEFAULT_IDS)
    print(f"Using ids={sorted(allowed_ids)}")

    times = parse_lines(args.path, allowed_ids=allowed_ids)
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

    res = plot_home_raster(
        home_intervals, bin_minutes=args.bin_minutes, out=args.out, show=args.show
    )
    if not args.show:
        print("Wrote", res)


if __name__ == "__main__":
    main()
