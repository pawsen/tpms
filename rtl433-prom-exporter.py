#!/usr/bin/env python3

import json, sys
from prometheus_client import Gauge, Counter, start_http_server

temp_c = Gauge("rtl433_temperature_c", "Temperature (C)", ["model","protocol","id","channel","type"])
humidity = Gauge("rtl433_humidity_percent", "Humidity (%)", ["model","protocol","id","channel","type"])
pressure_psi = Gauge("rtl433_pressure_psi", "Pressure (PSI)", ["model","protocol","id","channel","type"])
last_seen = Gauge("rtl433_last_seen_seconds", "Last message time (unix seconds)", ["model","protocol","id","channel","type"])
messages_total = Counter("rtl433_messages_total", "Messages processed", ["model","protocol"])
parse_errors_total = Counter("rtl433_parse_errors_total", "Parse/processing errors")

def s(v): return "" if v is None else str(v)

def handle(o: dict):
    model = s(o.get("model"))
    protocol = s(o.get("protocol"))
    dev_id = s(o.get("id"))
    channel = s(o.get("channel"))
    msg_type = s(o.get("type"))

    messages_total.labels(model=model, protocol=protocol).inc()
    last_seen.labels(model=model, protocol=protocol, id=dev_id, channel=channel, type=msg_type).set_to_current_time()

    if o.get("temperature_C") is not None:
        temp_c.labels(model=model, protocol=protocol, id=dev_id, channel=channel, type=msg_type).set(float(o["temperature_C"]))
    elif o.get("temperature_F") is not None:
        f = float(o["temperature_F"])
        temp_c.labels(model=model, protocol=protocol, id=dev_id, channel=channel, type=msg_type).set((f - 32.0) * 5.0 / 9.0)

    if o.get("humidity") is not None:
        humidity.labels(model=model, protocol=protocol, id=dev_id, channel=channel, type=msg_type).set(float(o["humidity"]))

    if o.get("pressure_PSI") is not None:
        pressure_psi.labels(model=model, protocol=protocol, id=dev_id, channel=channel, type=msg_type).set(float(o["pressure_PSI"]))

def main():
    start_http_server(9123, addr="0.0.0.0")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                handle(obj)
        except Exception:
            parse_errors_total.inc()

if __name__ == "__main__":
    main()
