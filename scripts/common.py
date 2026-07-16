from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR.parent  # raw CSVs sit one directory above the project
DERIVED_DIR = PROJECT_DIR / "derived"
FIGURES_DIR = PROJECT_DIR / "figures"

RAW_FILES = {
    "initial_evap": "v10_ullmann_initial_evap.csv",
    "lh_and_evap": "v10_ullmann_gilson_lh_and_evap.csv",
}

# The V-10 logs 31 signals at ~1 Hz. Some never move; we keep them in the DB
# (raw data is sacred) but exclude them from change detection.
ANALYSIS_CHANNELS = [
    "vacuumPressure",     # mbar — the star of an evaporation trace
    "vialTemp",           # °C  — IR sensor on the vial
    "avgVialTemp",        # °C  — smoothed vial temperature
    "headTemp",           # °C
    "condenserTemp",      # °C  — cold trap
    "vialHeaterTemp",     # °C
    "interconnectionTemp",
    "couplingTemp",
    "measuredSpeed",      # vortex/rotation speed feedback
    "targetSpeed",        # vortex/rotation speed setpoint
    "heaterFanSpeed",
    "scavengeFan1Speed",
    "scavengeFan2Speed",
    "powerMon",
    "elevatorHeight",
]

# Discrete/state channels: a *transition* is the event, not a derivative.
STATE_CHANNELS = ["instrumentState", "carouselStatus", "homeOpto",
                  "vialLoadedSwitch", "noVialOpto"]

# Change-detection parameters (tuned on this dataset; see REPORT.md §3).
SMOOTH_WINDOW_S = 5     # rolling-median window to kill single-sample spikes
Z_THRESHOLD = 4.0       # robust z-score on the derivative that counts as "change"
MIN_EVENT_S = 3         # discard blips shorter than this
MERGE_GAP_S = 5         # merge events separated by less than this


def load_run(run_id):
    df = pd.read_csv(DATA_DIR / RAW_FILES[run_id])
    df["ts"] = pd.to_datetime(df["timestamp_local"])
    # seconds since start of run — convenient x-axis for plots and rates
    df["t_s"] = (df["ts"] - df["ts"].iloc[0]).dt.total_seconds()
    df["run_id"] = run_id
    return df


def robust_z(x):
    """z-score using median/MAD instead of mean/std.

    Telemetry derivatives are mostly ~0 with rare huge excursions, so an
    ordinary std would be inflated by the very events we want to find.
    MAD (median absolute deviation) ignores them. 1.4826 rescales MAD to
    be comparable to a standard deviation for Gaussian noise.
    """
    med = np.nanmedian(x)
    mad = np.nanmedian(np.abs(x - med))
    scale = 1.4826 * mad
    if scale == 0 or np.isnan(scale):
        # channel with almost no noise floor: fall back to std, then to 1
        scale = np.nanstd(x) or 1.0
    return (x - med) / scale
