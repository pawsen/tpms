import json
from datetime import datetime, timedelta
from collections import defaultdict


def parse_lines(path):
    rows = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)

            t = datetime.fromisoformat(obj["time"])
            sid = obj.get("id")

            rssi = obj.get("rssi", None)
            rssi = float(rssi) if rssi is not None else None

            rows.append((t, sid, rssi))
    rows.sort(key=lambda x: x[0])
    return rows


def detect_home_intervals(
    rows,
    bin_seconds=60,
    rssi_gate=-12.0,  # only count packets stronger than this
    tau_minutes=30.0,  # decay time constant
    enter_score=0.7,
    exit_score=0.3,
    enter_hold_minutes=5,
    exit_hold_minutes=20,
):
    """
    Presence score S in [0,1]:
      - decays exponentially with time constant tau
      - increases when 'near' evidence occurs in a bin
    """
    if not rows:
        return []

    # Bin evidence per minute
    start = rows[0][0].replace(second=0, microsecond=0)
    end = rows[-1][0].replace(second=0, microsecond=0) + timedelta(minutes=1)

    # evidence[tbin] = (max_rssi, count, unique_ids)
    evidence = defaultdict(
        lambda: {"max_rssi": float("-inf"), "count": 0, "ids": set()}
    )

    for t, sid, rssi in rows:
        tbin = t.replace(second=0, microsecond=0)
        e = evidence[tbin]
        e["count"] += 1
        if sid:
            e["ids"].add(sid)
        if rssi is not None:
            e["max_rssi"] = max(e["max_rssi"], rssi)

    # scoring + hysteresis
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
        # near evidence: strong packet + optionally require multiple IDs over a window later
        has_rssi = e["max_rssi"] != float("-inf")
        near = (e["max_rssi"] >= rssi_gate) if has_rssi else (e["count"] >= 1)

        # update score
        S *= decay
        if near:
            # push score upward; clamp to 1
            S = min(1.0, S + 0.2)

        # hysteresis with hold times
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

    # close if still home
    if state == "HOME" and current_start is not None:
        intervals.append((current_start, end))

    return intervals


# Example usage:
rows = parse_lines("cleaned.jsonl")
home_intervals = detect_home_intervals(rows, rssi_gate=-12.0)
for a, b in home_intervals[:10]:
    print(a, "->", b, (b - a))


from plots import plot_home_raster

png = plot_home_raster(home_intervals, bin_minutes=5, out="home_raster.png", show=True)
print("Wrote", png)
