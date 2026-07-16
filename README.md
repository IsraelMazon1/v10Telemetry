# V-10 Telemetry Database Project

Parses Biotage V-10 evaporator telemetry CSVs, detects the scientifically
interesting high-change regions, loads everything into both **PostgreSQL**
and **MongoDB**, and compares the two. Full explanation in `REPORT.md`.

## Layout

```
v10_db_project/
├── README.md            this file
├── REPORT.md            the full writeup — read this
├── requirements.txt
├── sql/schema.sql       Postgres DDL
├── scripts/
│   ├── common.py            shared config + helpers
│   ├── 01_detect_events.py  change detection → derived/*.csv
│   ├── 02_plots.py          figures → figures/*.png
│   ├── 03_postgres.py       Postgres schema + load + 5 science queries
│   └── 04_mongo.py          Mongo documents + load + same 5 queries
├── derived/             computed tables (events, segments, run summary)
└── figures/             plots
```

## Running it

```bash
pip install -r requirements.txt
cd scripts

python3 01_detect_events.py     # 1. detect events/segments (writes derived/)
python3 02_plots.py             # 2. make figures

# 3. Postgres (macOS: brew install postgresql@16 && brew services start postgresql@16)
python3 03_postgres.py --port 5432 --user $(whoami)

# 4. MongoDB (macOS: brew tap mongodb/brew && brew install mongodb-community
#             && brew services start mongodb-community)
python3 04_mongo.py                       # real server on localhost:27017
python3 04_mongo.py --mock                # or in-memory, no server needed
```

Scripts 01–02 only need the raw CSVs in the parent folder. Scripts 03–04
need `derived/`, so run 01 first.
