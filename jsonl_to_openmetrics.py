#!/usr/bin/env python3
import json
import sys
from datetime import datetime, timezone, timedelta

LOCAL_TZ = timezone(timedelta(hours=1))  # logs are UTC+1

def parse_time_iso(s: str) -> int:
    # Example: "2026-02-05T17:47:05" (no TZ suffix)
    # Interpret as UTC+1, convert to UTC epoch seconds.
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)
    dt_utc = dt.astimezone(timezone.utc)
    return int(dt_utc.timestamp())

def esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

def build_labels(obj: dict) -> dict:
    # Keep labels stable and reasonably bounded.
    # Warning: including freq/rssi/snr/noise as labels would explode cardinality. Don't.
    labels = {}
    # Mirror what your exporter already does where possible:
    if "model" in obj:    labels["model"] = str(obj["model"])
    if "id" in obj:       labels["id"] = str(obj["id"])
    if "channel" in obj:  labels["channel"] = str(obj["channel"])
    if "type" in obj:     labels["type"] = str(obj["type"])
    if "protocol" in obj: labels["protocol"] = str(obj["protocol"])
    return labels

def fmt_labels(labels: dict) -> str:
    if not labels:
        return ""
    parts = [f'{k}="{esc(labels[k])}"' for k in sorted(labels.keys())]
    return "{" + ",".join(parts) + "}"

# Emit HELP/TYPE headers once per metric
print('# HELP rtl433_temperature_c Temperature in Celsius (backfilled from rtl_433 JSONL)')
print('# TYPE rtl433_temperature_c gauge')
print('# HELP rtl433_pressure_psi Pressure in PSI (backfilled from rtl_433 JSONL)')
print('# TYPE rtl433_pressure_psi gauge')
print('# HELP rtl433_humidity_percent Relative humidity in percent (backfilled from rtl_433 JSONL)')
print('# TYPE rtl433_humidity_percent gauge')

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue

    obj = json.loads(line)
    if "time" not in obj:
        continue

    ts = parse_time_iso(obj["time"])
    labels = build_labels(obj)
    lab = fmt_labels(labels)

    # temperature_C present in many devices
    if "temperature_C" in obj:
        try:
            v = float(obj["temperature_C"])
            print(f"rtl433_temperature_c{lab} {v} {ts}")
        except Exception:
            pass

    # Some devices may only have temperature_F; optionally convert
    elif "temperature_F" in obj:
        try:
            f = float(obj["temperature_F"])
            c = (f - 32.0) * (5.0 / 9.0)
            print(f"rtl433_temperature_c{lab} {c} {ts}")
        except Exception:
            pass

    # TPMS pressure
    if "pressure_PSI" in obj:
        try:
            v = float(obj["pressure_PSI"])
            print(f"rtl433_pressure_psi{lab} {v} {ts}")
        except Exception:
            pass

    # humidity
    if "humidity" in obj:
        try:
            v = float(obj["humidity"])
            print(f"rtl433_humidity_percent{lab} {v} {ts}")
        except Exception:
            pass

print("# EOF")
