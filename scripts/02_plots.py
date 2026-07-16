"""
02_plots.py — visualize the telemetry and the detected events.

Produces (in figures/):
    overview_<run_id>.png   4 stacked channels vs time, event regions shaded
    activity_<run_id>.png   composite activity index + PELT segment boundaries
    cycles_lh_and_evap.png  the ~7 evaporation cycles overlaid on one axis
    zoom_pressure_drop.png  close-up of a single pump-down event
Run 01_detect_events.py first.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from common import DERIVED_DIR, FIGURES_DIR, RAW_FILES, load_run

PLOT_CHANNELS = [
    ("vacuumPressure", "Vacuum pressure (mbar)", "log"),
    ("vialTemp", "Vial temp (°C)", "linear"),
    ("measuredSpeed", "Vortex speed", "linear"),
    ("condenserTemp", "Condenser temp (°C)", "linear"),
]


def shade_events(ax, events, channel):
    for _, ev in events[(events.channel == channel) &
                        (events.kind == "ramp")].iterrows():
        ax.axvspan(ev.start_t_s / 60, (ev.start_t_s + ev.duration_s) / 60,
                   alpha=0.25, color="tab:red", lw=0)


def overview(run_id, df, events):
    fig, axes = plt.subplots(len(PLOT_CHANNELS), 1, figsize=(12, 9),
                             sharex=True)
    for ax, (ch, label, scale) in zip(axes, PLOT_CHANNELS):
        ax.plot(df.t_s / 60, df[ch], lw=0.8, color="tab:blue")
        ax.set_ylabel(label, fontsize=9)
        ax.set_yscale(scale)
        shade_events(ax, events[events.run_id == run_id], ch)
        ax.grid(alpha=0.3)
    axes[0].set_title(
        f"{run_id} — {RAW_FILES[run_id]}\n"
        "red shading = detected high-change events")
    axes[-1].set_xlabel("minutes since start")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / f"overview_{run_id}.png", dpi=130)
    plt.close(fig)


def activity_plot(run_id, df, activity, segments):
    fig, ax = plt.subplots(figsize=(12, 3.5))
    a = activity[activity.run_id == run_id]
    ax.plot(a.t_s / 60, a.activity, lw=0.8, color="tab:purple")
    for t in segments[segments.run_id == run_id].start_ts:
        t_s = (pd.to_datetime(t) - df.ts.iloc[0]).total_seconds()
        ax.axvline(t_s / 60, color="k", ls="--", lw=0.6, alpha=0.6)
    ax.set_xlabel("minutes since start")
    ax.set_ylabel("activity index (mean |z|)")
    ax.set_title(f"{run_id} — composite activity; dashed = PELT segment boundaries")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / f"activity_{run_id}.png", dpi=130)
    plt.close(fig)


def cycles_overlay(df, segments):
    """Overlay each pump-down cycle of the long run to show reproducibility."""
    segs = segments[(segments.run_id == "lh_and_evap")].reset_index()
    # a cycle starts whenever mean_pressure drops below 600 after an idle seg
    fig, ax = plt.subplots(figsize=(10, 5))
    n = 0
    idle = True
    for _, s in segs.iterrows():
        if s.mean_pressure > 900:
            idle = True
            continue
        if idle:  # first active segment after idle = new cycle start
            start = (pd.to_datetime(s.start_ts) - df.ts.iloc[0]).total_seconds()
            window = df[(df.t_s >= start) & (df.t_s <= start + 240)]
            ax.plot(window.t_s - start, window.vacuumPressure,
                    lw=1, label=f"cycle {n + 1}")
            n += 1
            idle = False
    ax.set_yscale("log")
    ax.set_xlabel("seconds since cycle start")
    ax.set_ylabel("vacuum pressure (mbar)")
    ax.set_title("lh_and_evap — pump-down cycles overlaid (first 4 min of each)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3, which="both")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "cycles_lh_and_evap.png", dpi=130)
    plt.close(fig)


def zoom(df, events):
    """Close-up of the largest pressure drop with vial temp on twin axis."""
    ev = events[(events.channel == "vacuumPressure") &
                (events.direction == "down") &
                (events.run_id == "lh_and_evap")]
    ev = ev.loc[ev.duration_s.idxmax()]
    t0, t1 = ev.start_t_s - 30, ev.start_t_s + ev.duration_s + 60
    w = df[(df.t_s >= t0) & (df.t_s <= t1)]

    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(w.t_s / 60, w.vacuumPressure, color="tab:blue", label="pressure")
    ax.set_yscale("log")
    ax.set_ylabel("vacuum pressure (mbar)", color="tab:blue")
    ax2 = ax.twinx()
    ax2.plot(w.t_s / 60, w.vialTemp, color="tab:orange", label="vial temp")
    ax2.set_ylabel("vial temp (°C)", color="tab:orange")
    ax.axvspan(ev.start_t_s / 60, (ev.start_t_s + ev.duration_s) / 60,
               alpha=0.15, color="tab:red")
    ax.set_xlabel("minutes since start")
    ax.set_title("Largest pump-down event: evaporative cooling of the vial\n"
                 f"{ev.value_start:.0f} → {ev.value_end:.0f} mbar in "
                 f"{ev.duration_s:.0f} s (peak {ev.peak_rate_per_s:.0f} mbar/s)")
    ax.grid(alpha=0.3, which="both")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "zoom_pressure_drop.png", dpi=130)
    plt.close(fig)


def main():
    FIGURES_DIR.mkdir(exist_ok=True)
    events = pd.read_csv(DERIVED_DIR / "events.csv")
    segments = pd.read_csv(DERIVED_DIR / "segments.csv")
    activity = pd.read_csv(DERIVED_DIR / "activity.csv")

    for run_id in RAW_FILES:
        df = load_run(run_id)
        overview(run_id, df, events)
        activity_plot(run_id, df, activity, segments)
        if run_id == "lh_and_evap":
            cycles_overlay(df, segments)
            zoom(df, events)
    print("figures written to", FIGURES_DIR)


if __name__ == "__main__":
    main()
