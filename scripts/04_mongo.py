"""
04_mongo.py — MongoDB structure for the same data, plus the same five
benchmark science queries.

Usage:
    python3 04_mongo.py                          # real server on localhost:27017
    python3 04_mongo.py --uri mongodb://host:port
    python3 04_mongo.py --mock                   # in-memory mongomock (no server)

Document design (see REPORT.md §5):
    runs       one document per run; segments EMBEDDED as an array
               (segments are only ever read together with their run)
    telemetry  one document per 1 Hz sample; indexed on (run_id, ts)
               (on a real server, a native time-series collection or the
                bucket pattern would cut storage — noted in the report)
    events     separate collection — we query events independently of runs,
               so embedding them would force reading whole run docs
"""
import argparse
import time
from datetime import datetime

import pandas as pd

from common import DERIVED_DIR, RAW_FILES, load_run


def to_dt(x):
    """Mongo stores native datetimes — convert pandas timestamps."""
    return pd.to_datetime(x).to_pydatetime()


def load(db):
    db.runs.drop(); db.telemetry.drop(); db.events.drop()

    runs = pd.read_csv(DERIVED_DIR / "run_summary.csv")
    segments = pd.read_csv(DERIVED_DIR / "segments.csv")
    events = pd.read_csv(DERIVED_DIR / "events.csv")

    for _, r in runs.iterrows():
        segs = segments[segments.run_id == r.run_id]
        db.runs.insert_one({
            "_id": r.run_id,
            "source_file": r.source_file,
            "started_at": to_dt(r.started_at),
            "ended_at": to_dt(r.ended_at),
            "duration_s": r.duration_s,
            "n_samples": int(r.n_samples),
            "segments": [
                {"idx": int(s.segment_idx),
                 "start": to_dt(s.start_ts), "end": to_dt(s.end_ts),
                 "duration_s": s.duration_s,
                 "mean_pressure": s.mean_pressure,
                 "mean_vial_temp": s.mean_vial_temp,
                 "mean_speed": s.mean_speed,
                 "dominant_state": int(s.dominant_state)}
                for _, s in segs.iterrows()],
        })

    ev_docs = events.to_dict("records")
    for d in ev_docs:
        d["_id"] = d.pop("event_id")
        d["start_ts"] = to_dt(d["start_ts"])
        d["end_ts"] = to_dt(d["end_ts"])
    db.events.insert_many(ev_docs)
    db.events.create_index([("run_id", 1), ("channel", 1)])
    db.events.create_index([("channel", 1), ("peak_rate_per_s", 1)])

    t0 = time.time()
    n = 0
    for run_id in RAW_FILES:
        df = load_run(run_id)
        docs = [{
            "run_id": run_id,
            "ts": to_dt(row["ts"]),
            "seq": int(row["_seq"]),
            # keep original camelCase field names — no schema to migrate!
            **{c: row[c] for c in df.columns
               if c not in ("ts", "t_s", "run_id", "_seq",
                            "_timestamp", "timestamp_local",
                            "unknown_default")},
        } for row in df.to_dict("records")]
        db.telemetry.insert_many(docs)
        n += len(docs)
    db.telemetry.create_index([("run_id", 1), ("ts", 1)])
    print(f"loaded {n} telemetry docs in {time.time() - t0:.2f}s, "
          f"{len(ev_docs)} events, {len(runs)} runs\n")


def queries(db):
    t0 = time.time()
    q1 = list(db.events
              .find({"channel": "vacuumPressure", "direction": "down"},
                    {"run_id": 1, "start_ts": 1, "duration_s": 1,
                     "value_start": 1, "value_end": 1, "peak_rate_per_s": 1})
              .sort("peak_rate_per_s", 1).limit(5))
    print(f"--- Q1 five fastest pressure drops  [{(time.time()-t0)*1e3:.1f} ms]")
    for d in q1:
        print(f"    {d['run_id']} {d['start_ts']} {d['duration_s']:.0f}s "
              f"{d['value_start']:.1f}->{d['value_end']:.1f} mbar "
              f"peak {d['peak_rate_per_s']:.1f}/s")

    # No SQL-style range JOIN in Mongo: the idiomatic pattern for Q2 is one
    # query per event (application-side join). This is the big ergonomic
    # difference vs Postgres — see REPORT.md §6.
    t0 = time.time()
    rows = []
    for ev in db.events.find({"channel": "vacuumPressure", "direction": "down"}):
        temps = [d["vialTemp"] for d in db.telemetry.find(
            {"run_id": ev["run_id"],
             "ts": {"$gte": ev["start_ts"], "$lte": ev["end_ts"]}},
            {"vialTemp": 1})]
        if temps:
            rows.append((ev["_id"], ev["run_id"], ev["start_ts"],
                         min(temps), sum(temps) / len(temps)))
    rows.sort(key=lambda r: r[3])
    print(f"\n--- Q2 vial temp during pressure drops (app-side join) "
          f"[{(time.time()-t0)*1e3:.1f} ms]")
    for r in rows[:5]:
        print(f"    ev{r[0]} {r[1]} {r[2]} coldest {r[3]:.1f}C mean {r[4]:.1f}C")

    t0 = time.time()
    q3 = list(db.events.aggregate([
        {"$match": {"kind": "ramp"}},
        {"$group": {"_id": {"run": "$run_id", "ch": "$channel"},
                    "n_events": {"$sum": 1},
                    "total_active_s": {"$sum": "$duration_s"}}},
        {"$sort": {"n_events": -1}},
        {"$limit": 8},
    ]))
    print(f"\n--- Q3 event counts per run/channel  [{(time.time()-t0)*1e3:.1f} ms]")
    for d in q3:
        print(f"    {d['_id']['run']:<14} {d['_id']['ch']:<20} "
              f"n={d['n_events']:<3} active={d['total_active_s']:.0f}s")

    t0 = time.time()
    q4 = list(db.telemetry.find(
        {"run_id": "lh_and_evap",
         "ts": {"$gte": datetime(2026, 6, 2, 18, 0),
                "$lte": datetime(2026, 6, 2, 18, 2)}},
        {"ts": 1, "vacuumPressure": 1, "vialTemp": 1}).sort("ts", 1))
    print(f"\n--- Q4 raw slice (2-min window, {len(q4)} docs)  "
          f"[{(time.time()-t0)*1e3:.1f} ms]")
    for d in q4[:3]:
        print(f"    {d['ts']} {d['vacuumPressure']:.4f} {d['vialTemp']}")

    t0 = time.time()
    q5 = list(db.telemetry.aggregate([
        {"$match": {"condenserTemp": {"$gt": -34}, "instrumentState": 3}},
        {"$group": {"_id": "$run_id", "warm_samples": {"$sum": 1},
                    "warmest_c": {"$max": "$condenserTemp"}}},
    ]))
    print(f"\n--- Q5 condenser excursions while running  "
          f"[{(time.time()-t0)*1e3:.1f} ms]")
    for d in q5:
        print(f"    {d['_id']:<14} n={d['warm_samples']} "
              f"warmest={d['warmest_c']:.1f}C")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uri", default="mongodb://localhost:27017")
    ap.add_argument("--mock", action="store_true",
                    help="use in-memory mongomock instead of a server")
    args = ap.parse_args()

    if args.mock:
        import mongomock
        print("[using mongomock — same API, in-memory; "
              "rerun without --mock against a real server]\n")
        client = mongomock.MongoClient()
    else:
        import pymongo
        client = pymongo.MongoClient(args.uri, serverSelectionTimeoutMS=3000)
    db = client.v10_telemetry
    load(db)
    queries(db)


if __name__ == "__main__":
    main()
