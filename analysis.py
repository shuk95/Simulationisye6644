"""
analysis.py
===========
Experiment driver for the fast-food simulation.

Runs every scenario, aggregates replications into summary statistics with
95% confidence intervals, checks Little's Law, and produces the report
figures.

This version is written to run cleanly in Google Colab, Jupyter, or VS Code,
whether the files are all in one folder (Colab-style) or in the original
src/ + results/ project layout.

ISYE 6644 - Topic 5: Fast Food Simulation
Team: Nahom Sososa, Neil Shukla
"""

import os
import sys

# Make sure sibling modules (config.py, simulation.py) can be imported,
# regardless of how the notebook / script is launched.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
for _p in (_THIS_DIR, os.getcwd()):
    if _p not in sys.path:
        sys.path.append(_p)

import matplotlib
matplotlib.use("Agg")                # headless backend; saves PNGs without a display
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# --- Correct imports --------------------------------------------------------
# We need the parameters (config) and two functions from the simulation engine.
import config
from simulation import run_scenario, summarize


# ---------------------------------------------------------------------------
# Output locations (robust to both project layouts)
# ---------------------------------------------------------------------------
def _find_results_dir():
    """Pick a sensible results/ directory and make sure it exists.

    Priority:
      1. an existing ../results   (original src/ + results/ repo layout)
      2. an existing ./results
      3. otherwise create ./results next to this file / the working dir
    """
    candidates = [
        os.path.normpath(os.path.join(_THIS_DIR, "..", "results")),
        os.path.normpath(os.path.join(_THIS_DIR, "results")),
        os.path.normpath(os.path.join(os.getcwd(), "results")),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    chosen = candidates[1]                     # default: ./results beside this file
    os.makedirs(os.path.join(chosen, "plots"), exist_ok=True)
    return chosen


RESULTS = _find_results_dir()
PLOTS = os.path.join(RESULTS, "plots")
os.makedirs(PLOTS, exist_ok=True)
print(f"[analysis] writing results to: {RESULTS}")

# Consistent, readable styling for all figures.
plt.rcParams.update({
    "figure.dpi": 130,
    "font.size": 10,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "axes.axisbelow": True,
})
BAR = "#C8102E"       # accent
BAR2 = "#1D3557"      # secondary


def run_all():
    """Run every scenario; return (per_rep_df, summary_df)."""
    per_rep_frames, summary_rows = [], []
    for cfg in config.SCENARIOS:
        print(f"Running: {cfg['name']} ...")
        df = run_scenario(cfg)
        per_rep_frames.append(df)
        summary_rows.append(summarize(df))
    per_rep = pd.concat(per_rep_frames, ignore_index=True)
    summary = pd.DataFrame(summary_rows)
    return per_rep, summary


def littles_law_check(per_rep):
    """Validate each scenario with Little's Law: L ?= lambda_eff * W.

    lambda_eff is the achieved throughput (customers/min), estimated from
    each replication, so the identity should hold to within sampling error.
    """
    rows = []
    for cfg in config.SCENARIOS:
        sub = per_rep[per_rep["scenario"] == cfg["name"]]
        L = sub["avg_num_in_system"].mean()
        W = sub["avg_time_in_system"].mean()
        lam_eff = sub["throughput_per_hr"].mean() / 60.0     # per minute
        L_pred = lam_eff * W
        rows.append({
            "scenario": cfg["name"],
            "L_observed": L,
            "lambda_eff_x_W": L_pred,
            "abs_pct_error": abs(L - L_pred) / L * 100 if L else float("nan"),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
def _order():
    return [c["name"] for c in config.SCENARIOS]


def fig_time_in_system(summary):
    order = _order()
    s = summary.set_index("scenario").loc[order]
    means = s["avg_time_in_system_mean"].to_numpy()
    hw = s["avg_time_in_system_hw"].to_numpy()

    fig, ax = plt.subplots(figsize=(8, 4.2))
    x = np.arange(len(order))
    ax.bar(x, means, yerr=hw, capsize=4, color=BAR, alpha=0.9,
           error_kw={"ecolor": "#333", "elinewidth": 1})
    ax.set_xticks(x)
    ax.set_xticklabels(order, rotation=18, ha="right")
    ax.set_ylabel("Avg time in system (min)")
    ax.set_title("Average customer time in system by scenario\n(error bars = 95% CI)")
    for xi, mv in zip(x, means):
        ax.text(xi, mv, f"{mv:.1f}", ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    path = os.path.join(PLOTS, "time_in_system.png")
    fig.savefig(path); plt.close(fig)
    return path


def fig_wait_breakdown(summary):
    order = _order()
    s = summary.set_index("scenario").loc[order]
    cash = s["avg_wait_cashier_mean"].to_numpy()
    kit = s["avg_wait_kitchen_mean"].to_numpy()
    pick = s["avg_wait_pickup_mean"].to_numpy()

    fig, ax = plt.subplots(figsize=(8, 4.2))
    x = np.arange(len(order))
    ax.bar(x, cash, label="Cashier queue", color=BAR2)
    ax.bar(x, kit, bottom=cash, label="Kitchen queue", color=BAR)
    ax.bar(x, pick, bottom=cash + kit, label="Pickup queue", color="#F4A261")
    ax.set_xticks(x); ax.set_xticklabels(order, rotation=18, ha="right")
    ax.set_ylabel("Avg queueing delay (min)")
    ax.set_title("Where customers wait: queueing delay by stage")
    ax.legend()
    fig.tight_layout()
    path = os.path.join(PLOTS, "wait_breakdown.png")
    fig.savefig(path); plt.close(fig)
    return path


def fig_utilization(summary):
    order = _order()
    s = summary.set_index("scenario").loc[order]
    cash = s["util_cashier_mean"].to_numpy()
    kit = s["util_kitchen_mean"].to_numpy()
    pick = s["util_pickup_mean"].to_numpy()

    fig, ax = plt.subplots(figsize=(8, 4.2))
    x = np.arange(len(order)); w = 0.26
    ax.bar(x - w, cash, w, label="Cashiers", color=BAR2)
    ax.bar(x, kit, w, label="Kitchen", color=BAR)
    ax.bar(x + w, pick, w, label="Pickup", color="#F4A261")
    ax.axhline(1.0, color="#888", ls="--", lw=1)
    ax.text(len(order) - 0.5, 1.005, "capacity", color="#888",
            ha="right", va="bottom", fontsize=8)
    ax.set_xticks(x); ax.set_xticklabels(order, rotation=18, ha="right")
    ax.set_ylabel("Utilization")
    ax.set_ylim(0, 1.25)
    ax.set_title("Resource utilization by scenario")
    ax.legend(ncol=3, loc="upper left")
    fig.tight_layout()
    path = os.path.join(PLOTS, "utilization.png")
    fig.savefig(path); plt.close(fig)
    return path


def fig_convergence():
    """Cumulative-mean of time-in-system across replications (baseline)."""
    cfg = config.BASELINE
    df = run_scenario(cfg)
    vals = df["avg_time_in_system"].to_numpy()
    cummean = np.cumsum(vals) / (np.arange(len(vals)) + 1)

    fig, ax = plt.subplots(figsize=(8, 4.0))
    reps = np.arange(1, len(vals) + 1)
    ax.plot(reps, cummean, "-o", color=BAR, ms=4, label="cumulative mean")
    ax.axhline(cummean[-1], color=BAR2, ls="--", lw=1,
               label=f"final estimate = {cummean[-1]:.2f} min")
    ax.set_xlabel("Number of replications")
    ax.set_ylabel("Avg time in system (min)")
    ax.set_title("Convergence of the mean estimate (baseline)")
    ax.legend()
    fig.tight_layout()
    path = os.path.join(PLOTS, "convergence.png")
    fig.savefig(path); plt.close(fig)
    return path


def fig_wait_distribution():
    """Histogram of per-replication mean time-in-system, baseline vs peak."""
    base = run_scenario(config.BASELINE)["avg_time_in_system"]
    peak = run_scenario(config.SCENARIOS[1])["avg_time_in_system"]  # peak demand

    fig, ax = plt.subplots(figsize=(8, 4.0))
    bins = np.linspace(min(base.min(), peak.min()),
                       max(base.max(), peak.max()), 14)
    ax.hist(base, bins=bins, alpha=0.7, color=BAR2, label="Baseline (45/hr)")
    ax.hist(peak, bins=bins, alpha=0.7, color=BAR, label="Peak demand (60/hr)")
    ax.set_xlabel("Replication-mean time in system (min)")
    ax.set_ylabel("Frequency (replications)")
    ax.set_title("Sampling distribution of mean time in system")
    ax.legend()
    fig.tight_layout()
    path = os.path.join(PLOTS, "wait_distribution.png")
    fig.savefig(path); plt.close(fig)
    return path


def main():
    per_rep, summary = run_all()

    per_rep.to_csv(os.path.join(RESULTS, "per_replication.csv"), index=False)
    summary.to_csv(os.path.join(RESULTS, "scenario_summary.csv"), index=False)

    ll = littles_law_check(per_rep)
    ll.to_csv(os.path.join(RESULTS, "littles_law.csv"), index=False)
    print("\nLittle's Law check (L vs lambda_eff * W):")
    print(ll.to_string(index=False))

    print("\nGenerating figures ...")
    for f in (fig_time_in_system, fig_wait_breakdown, fig_utilization):
        print("  ", f(summary))
    for f in (fig_convergence, fig_wait_distribution):
        print("  ", f())

    print("\nAll results written to", RESULTS)


if __name__ == "__main__":
    main()
