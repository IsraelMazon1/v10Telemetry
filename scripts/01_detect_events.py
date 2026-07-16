"""
01_detect_events.py — find and quantify the regions of high change.

Strategy (explained in depth in REPORT.md §3):

1. Per continuous channel:  smooth → differentiate → robust z-score of the
   derivative → threshold → contiguous above-threshold samples become an
   *event*. Each event is summarised (duration, delta, peak rate, ...).
2. Per state channel:       every transition (value change) is an event.
3. Per run:                 a composite "activity index" (mean |z| across
   channels) and PELT change-point segmentation (ruptures) that cuts the
   run into quasi-stationary *segments* — the phases of the experiment.

Outputs (CSV in derived/):
    events.csv       one row per detected event
    segments.csv     one row per PELT segment per run
    run_summary.csv  one row per run
    activity.csv     per-sample activity index (for plotting)
"""
import numpy as np
import pandas as pd
import ruptures as rpt

from common import (ANALYSIS_CHANNELS, STATE_CHANNELS, DERIVED_DIR,
                    MERGE_GAP_S, MIN_EVENT_S, RAW_FILES, SMOOTH_WINDOW_S,
                    Z_THRESHOLD, load_run, robust_z)


def contiguous_regions(mask):
    """Return [start, end) index pairs for runs of True in a boolean mask."""
    idx = np.flatnonzero(np.diff(np.r_[False, mask, False]))
    return list(zip(idx[::2], idx[1::2]))


def merge_close(regions, max_gap):
    """Merge regions whose gap is <= max_gap samples (1 sample ≈ 1 s)."""
    merged = []
    for s, e in regions:
        if merged and s - merged[-1][1] <= max_gap:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged


def detect_channel_events(df, channel):
    """Threshold the robust-z of the smoothed derivative of one channel."""
    smooth = df[channel].rolling(SMOOTH_WINDOW_S, center=True,
                                 min_periods=1).median()
    deriv = np.gradient(smooth.to_numpy(), df["t_s"].to_numpy())
    z = robust_z(deriv)

    regions = contiguous_regions(np.abs(z) > Z_THRESHOLD)
    regions = merge_close(regions, MERGE_GAP_S)
    regions = [(s, e) for s, e in regions if e - s >= MIN_EVENT_S]

    events = []
    for s, e in regions:
        seg_raw = df[channel].iloc[s:e]
        seg_deriv = deriv[s:e]
        events.append({
            "run_id": df["run_id"].iloc[0],
            "channel": channel,
            "kind": "ramp",
            "start_ts": df["ts"].iloc[s],
            "end_ts": df["ts"].iloc[e - 1],
            "start_t_s": df["t_s"].iloc[s],
            "duration_s": df["t_s"].iloc[e - 1] - df["t_s"].iloc[s],
            "value_start": seg_raw.iloc[0],
            "value_end": seg_raw.iloc[-1],
            "delta": seg_raw.iloc[-1] - seg_raw.iloc[0],
            "value_min": seg_raw.min(),
            "value_max": seg_raw.max(),
            "peak_rate_per_s": seg_deriv[np.argmax(np.abs(seg_deriv))],
            "mean_abs_z": float(np.mean(np.abs(z[s:e]))),
            "direction": "up" if seg_raw.iloc[-1] >= seg_raw.iloc[0] else "down",
        })
    return events, z


def detect_state_transitions(df, channel):
    """For discrete channels every value change is an event of kind 'transition'."""
    changed = df[channel] != df[channel].shift()
    changed.iloc[0] = False
    events = []
    for i in np.flatnonzero(changed.to_numpy()):
        events.append({
            "run_id": df["run_id"].iloc[0],
            "channel": channel,
            "kind": "transition",
            "start_ts": df["ts"].iloc[i],
            "end_ts": df["ts"].iloc[i],
            "start_t_s": df["t_s"].iloc[i],
            "duration_s": 0.0,
            "value_start": df[channel].iloc[i - 1],
            "value_end": df[channel].iloc[i],
            "delta": df[channel].iloc[i] - df[channel].iloc[i - 1],
            "value_min": min(df[channel].iloc[i - 1], df[channel].iloc[i]),
            "value_max": max(df[channel].iloc[i - 1], df[channel].iloc[i]),
            "peak_rate_per_s": np.nan,
            "mean_abs_z": np.nan,
            "direction": "up" if df[channel].iloc[i] > df[channel].iloc[i - 1]
                         else "down",
        })
    return events


def segment_run(df, activity):
    """PELT change-point detection on the activity index → run phases."""
    algo = rpt.Pelt(model="rbf", min_size=30, jump=5).fit(
        activity.reshape(-1, 1))
    bkps = algo.predict(pen=10)          # penalty tuned for ~1 Hz lab data
    segments, start = [], 0
    for end in bkps:
        seg = df.iloc[start:end]
        segments.append({
            "run_id": df["run_id"].iloc[0],
            "segment_idx": len(segments),
            "start_ts": seg["ts"].iloc[0],
            "end_ts": seg["ts"].iloc[-1],
            "duration_s": seg["t_s"].iloc[-1] - seg["t_s"].iloc[0],
            "mean_activity": float(activity[start:end].mean()),
            "mean_pressure": seg["vacuumPressure"].mean(),
            "mean_vial_temp": seg["vialTemp"].mean(),
            "mean_speed": seg["measuredSpeed"].mean(),
            "dominant_state": int(seg["instrumentState"].mode().iloc[0]),
        })
        start = end
    return segments


def main():
    DERIVED_DIR.mkdir(exist_ok=True)
    all_events, all_segments, run_rows, activity_rows = [], [], [], []

    for run_id in RAW_FILES:
        df = load_run(run_id)

        zs = {}
        for ch in ANALYSIS_CHANNELS:
            evs, z = detect_channel_events(df, ch)
            all_events += evs
            zs[ch] = np.abs(z)

        for ch in STATE_CHANNELS:
            all_events += detect_state_transitions(df, ch)

        activity = np.nanmean(np.column_stack(list(zs.values())), axis=1)
        all_segments += segment_run(df, activity)
        activity_rows.append(pd.DataFrame({
            "run_id": run_id, "ts": df["ts"], "t_s": df["t_s"],
            "activity": activity}))

        run_rows.append({
            "run_id": run_id,
            "source_file": RAW_FILES[run_id],
            "started_at": df["ts"].iloc[0],
            "ended_at": df["ts"].iloc[-1],
            "duration_s": df["t_s"].iloc[-1],
            "n_samples": len(df),
            "sample_rate_hz": round(len(df) / max(df["t_s"].iloc[-1], 1), 3),
        })

    events = pd.DataFrame(all_events).sort_values(["run_id", "start_ts"])
    events.insert(0, "event_id", range(1, len(events) + 1))
    events.to_csv(DERIVED_DIR / "events.csv", index=False)
    pd.DataFrame(all_segments).to_csv(DERIVED_DIR / "segments.csv", index=False)
    pd.DataFrame(run_rows).to_csv(DERIVED_DIR / "run_summary.csv", index=False)
    pd.concat(activity_rows).to_csv(DERIVED_DIR / "activity.csv", index=False)

    print(f"events:   {len(events)}")
    print(events.groupby(['run_id', 'kind']).size())
    print(f"segments: {len(all_segments)}")


if __name__ == "__main__":
    main()
