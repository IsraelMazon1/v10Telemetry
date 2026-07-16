"""
03_postgres.py — create the Postgres schema, load raw + derived data,
and run the five benchmark science queries.

Usage:
    python3 03_postgres.py [--host 127.0.0.1 --port 5432 --user postgres]

Requires: psycopg2-binary, a running Postgres server, and the outputs of
01_detect_events.py in derived/.
"""
import argparse
import io
import time

import pandas as pd
import psycopg2

from common import DERIVED_DIR, PROJECT_DIR, RAW_FILES, load_run

# csv column -> snake_case DB column (drop unknown_default & duplicates)
COLMAP = {
    "powerMon": "power_mon", "temp": "temp", "vialTemp": "vial_temp",
    "avgVialTemp": "avg_vial_temp", "headTemp": "head_temp",
    "instrumentState": "instrument_state",
    "instrumentInitState": "instrument_init_state",
    "vacuumPressure": "vacuum_pressure",
    "interconnectionTemp": "interconnection_temp",
    "couplingTemp": "coupling_temp", "vialHeaterTemp": "vial_heater_temp",
    "condenserTemp": "condenser_temp", "evapTimeElapsed": "evap_time_elapsed",
    "finalDryTimeLeft": "final_dry_time_left",
    "methodExState": "method_ex_state", "carouselStatus": "carousel_status",
    "vacuumPressureRaw": "vacuum_pressure_raw",
    "heaterFanSpeed": "heater_fan_speed",
    "scavengeFan1Speed": "scavenge_fan1_speed",
    "scavengeFan2Speed": "scavenge_fan2_speed",
    "measuredSpeed": "measured_speed", "targetSpeed": "target_speed",
    "noVialOpto": "no_vial_opto", "homeOpto": "home_opto",
    "vialLoadedSwitch": "vial_loaded_switch", "pumpHomeOpto": "pump_home_opto",
    "elevatorHeight": "elevator_height",
}

QUERIES = {
    "Q1 five fastest pressure drops": """
        SELECT run_id, start_ts, duration_s,
               round(value_start::numeric,1) AS from_mbar,
               round(value_end::numeric,1)   AS to_mbar,
               round(peak_rate_per_s::numeric,1) AS peak_mbar_per_s
        FROM events
        WHERE channel = 'vacuumPressure' AND direction = 'down'
        ORDER BY peak_rate_per_s ASC LIMIT 5;
    """,
    "Q2 vial temp behaviour during each pressure-drop event": """
        SELECT e.event_id, e.run_id, e.start_ts,
               round(min(t.vial_temp)::numeric,1) AS coldest_vial_c,
               round(avg(t.vial_temp)::numeric,1) AS mean_vial_c
        FROM events e
        JOIN telemetry t
          ON t.run_id = e.run_id AND t.ts BETWEEN e.start_ts AND e.end_ts
        WHERE e.channel = 'vacuumPressure' AND e.direction = 'down'
        GROUP BY e.event_id, e.run_id, e.start_ts
        ORDER BY coldest_vial_c LIMIT 5;
    """,
    "Q3 event counts and active seconds per run/channel": """
        SELECT run_id, channel, count(*) AS n_events,
               round(sum(duration_s)::numeric,0) AS total_active_s
        FROM events WHERE kind = 'ramp'
        GROUP BY run_id, channel
        ORDER BY n_events DESC LIMIT 8;
    """,
    "Q4 raw slice for plotting (2-min window)": """
        SELECT ts, vacuum_pressure, vial_temp
        FROM telemetry
        WHERE run_id = 'lh_and_evap'
          AND ts BETWEEN '2026-06-02 18:00:00' AND '2026-06-02 18:02:00'
        ORDER BY ts LIMIT 3;
    """,
    "Q5 condenser excursions while running": """
        SELECT run_id, count(*) AS warm_samples,
               round(max(condenser_temp)::numeric,1) AS warmest_c
        FROM telemetry
        WHERE condenser_temp > -34 AND instrument_state = 3
        GROUP BY run_id;
    """,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5432)
    ap.add_argument("--user", default="postgres")
    ap.add_argument("--dbname", default="postgres")
    args = ap.parse_args()

    conn = psycopg2.connect(host=args.host, port=args.port,
                            user=args.user, dbname=args.dbname)
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute((PROJECT_DIR / "sql" / "schema.sql").read_text())
    for t in ["segments", "events", "telemetry", "runs"]:
        cur.execute(f"TRUNCATE {t} CASCADE;")  # idempotent reload

    runs = pd.read_csv(DERIVED_DIR / "run_summary.csv")
    for _, r in runs.iterrows():
        cur.execute(
            "INSERT INTO runs VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (r.run_id, r.source_file, r.started_at, r.ended_at,
             r.duration_s, int(r.n_samples), r.sample_rate_hz))

    # telemetry is bulk-loaded via COPY; row INSERTs are far too slow here
    t0 = time.time()
    n = 0
    for run_id in RAW_FILES:
        df = load_run(run_id)
        out = pd.DataFrame({"run_id": df.run_id, "ts": df.ts, "seq": df._seq})
        for src, dst in COLMAP.items():
            # the logger writes everything as floats; cast true state/flag
            # channels back to integers so they load into smallint columns
            if dst in ("instrument_state", "instrument_init_state",
                       "method_ex_state", "carousel_status", "no_vial_opto",
                       "home_opto", "vial_loaded_switch", "pump_home_opto"):
                out[dst] = df[src].astype(int)
            else:
                out[dst] = df[src]
        buf = io.StringIO()
        out.to_csv(buf, index=False, header=False)
        buf.seek(0)
        cur.copy_expert(
            f"COPY telemetry ({','.join(['run_id','ts','seq'] + list(COLMAP.values()))}) "
            "FROM STDIN WITH CSV", buf)
        n += len(out)
    load_s = time.time() - t0

    ev = pd.read_csv(DERIVED_DIR / "events.csv")
    cols = ["event_id", "run_id", "channel", "kind", "start_ts", "end_ts",
            "duration_s", "value_start", "value_end", "delta", "value_min",
            "value_max", "peak_rate_per_s", "mean_abs_z", "direction"]
    buf = io.StringIO(); ev[cols].to_csv(buf, index=False, header=False)
    buf.seek(0)
    cur.copy_expert(f"COPY events ({','.join(cols)}) FROM STDIN WITH CSV NULL ''", buf)

    seg = pd.read_csv(DERIVED_DIR / "segments.csv")
    buf = io.StringIO(); seg.to_csv(buf, index=False, header=False)
    buf.seek(0)
    cur.copy_expert("COPY segments FROM STDIN WITH CSV", buf)

    print(f"loaded {n} telemetry rows in {load_s:.2f}s, "
          f"{len(ev)} events, {len(seg)} segments\n")

    for name, q in QUERIES.items():
        t0 = time.time()
        cur.execute(q)
        rows = cur.fetchall()
        ms = (time.time() - t0) * 1000
        print(f"--- {name}  [{ms:.1f} ms]")
        for row in rows:
            print("   ", row)
        print()

    conn.close()


if __name__ == "__main__":
    main()
