-- schema.sql — Postgres structure for V-10 telemetry
--
-- Three-layer design (see REPORT.md §4):
--   runs      one row per instrument run (one CSV = one run here)
--   telemetry raw 1 Hz samples, wide format (one column per channel)
--   events    derived high-change regions   <- the "scientific value" layer
--   segments  derived run phases from change-point detection

CREATE TABLE IF NOT EXISTS runs (
    run_id        text PRIMARY KEY,
    source_file   text NOT NULL,
    started_at    timestamptz NOT NULL,
    ended_at      timestamptz NOT NULL,
    duration_s    double precision,
    n_samples     integer,
    sample_rate_hz double precision
);

-- Wide table: the V-10 channel set is fixed per firmware version, so
-- columns are appropriate. If channel sets varied per instrument, a
-- narrow (run_id, ts, channel, value) layout or JSONB would fit better.
CREATE TABLE IF NOT EXISTS telemetry (
    run_id        text REFERENCES runs(run_id),
    ts            timestamptz NOT NULL,
    seq           bigint,
    power_mon             double precision,
    temp                  double precision,
    vial_temp             double precision,
    avg_vial_temp         double precision,
    head_temp             double precision,
    instrument_state      smallint,
    instrument_init_state smallint,
    vacuum_pressure       double precision,
    interconnection_temp  double precision,
    coupling_temp         double precision,
    vial_heater_temp      double precision,
    condenser_temp        double precision,
    evap_time_elapsed     double precision,
    final_dry_time_left   double precision,
    method_ex_state       smallint,
    carousel_status       smallint,
    vacuum_pressure_raw   double precision,
    heater_fan_speed      double precision,
    scavenge_fan1_speed   double precision,
    scavenge_fan2_speed   double precision,
    measured_speed        double precision,
    target_speed          double precision,
    no_vial_opto          smallint,
    home_opto             smallint,
    vial_loaded_switch    smallint,
    pump_home_opto        smallint,
    elevator_height       double precision,
    PRIMARY KEY (run_id, ts, seq)
);

-- Time-range scans are THE telemetry access pattern -> composite index.
CREATE INDEX IF NOT EXISTS telemetry_run_ts ON telemetry (run_id, ts);

CREATE TABLE IF NOT EXISTS events (
    event_id      integer PRIMARY KEY,
    run_id        text REFERENCES runs(run_id),
    channel       text NOT NULL,
    kind          text NOT NULL,        -- 'ramp' | 'transition'
    start_ts      timestamptz NOT NULL,
    end_ts        timestamptz NOT NULL,
    duration_s    double precision,
    value_start   double precision,
    value_end     double precision,
    delta         double precision,
    value_min     double precision,
    value_max     double precision,
    peak_rate_per_s double precision,
    mean_abs_z    double precision,
    direction     text
);

CREATE INDEX IF NOT EXISTS events_run_channel ON events (run_id, channel);
CREATE INDEX IF NOT EXISTS events_time ON events (start_ts, end_ts);

CREATE TABLE IF NOT EXISTS segments (
    run_id        text REFERENCES runs(run_id),
    segment_idx   integer,
    start_ts      timestamptz,
    end_ts        timestamptz,
    duration_s    double precision,
    mean_activity double precision,
    mean_pressure double precision,
    mean_vial_temp double precision,
    mean_speed    double precision,
    dominant_state smallint,
    PRIMARY KEY (run_id, segment_idx)
);
