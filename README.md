# ISYE 6644 — Project Topic 5: Fast-Food Restaurant Simulation

**Team 5 — Neil Shukla**

A discrete-event simulation of a fast-food restaurant built in Python with
SimPy. Customers arrive as a Poisson process and pass through three
service stages — **cashier** (order + pay), **kitchen** (food prep), and
**pickup** (hand-off) — each modeled as a limited-capacity resource. The
model is verified against the analytic M/M/1 queue, validated with Little's
Law, and used to run replicated what-if experiments on demand and staffing.

---

## Contents

| File | Description |
|------|-------------|
| `README.md` | This file. |
| `requirements.txt` | Python package dependencies. |
| `src/config.py` | All model parameters and the five what-if scenarios. Edit here to change staffing, arrival rates, distributions, run length, or number of replications. Also holds the M/M/1 validation settings. |
| `src/simulation.py` | Core SimPy engine. Defines the `FastFoodSim` model, the per-run statistics collector, the replication driver (`run_scenario`), confidence-interval summarizer (`summarize`), and the M/M/1 verification routine. Runnable from the command line. |
| `src/analysis.py` | Experiment driver. Runs every scenario, writes the summary CSVs, performs the Little's Law consistency check, and generates all figures used in the report. |
| `src/make_report.py` | Builds the final PDF report from the result CSVs and figures so the report always matches the actual simulation output. |
| `results/scenario_summary.csv` | Mean ± 95% CI half-width for every metric, per scenario. |
| `results/per_replication.csv` | Raw per-replication metrics for all scenarios (reproducibility). |
| `results/littles_law.csv` | Little's Law consistency check (L vs λ_eff × W). |
| `results/plots/*.png` | Figures: process flow, time in system, wait breakdown, utilization, convergence, sampling distribution. |

> The final report PDF is submitted **separately** from this zip, per the
> assignment instructions.

---

## How to run

From the project root:

```bash
# 1. install dependencies
pip install -r requirements.txt

# 2. verify the engine against the analytic M/M/1 queue
python src/simulation.py --validate

# 3. run a single scenario and print its metrics
python src/simulation.py --scenario baseline
python src/simulation.py --scenario "Peak + extra kitchen" --verbose

# 4. run the full experiment (all scenarios) and regenerate CSVs + figures
python src/analysis.py

# 5. rebuild the PDF report from the latest results
python src/make_report.py
```

Steps 4 and 5 write into `results/`. Running step 4 then step 5 regenerates
every number and figure in the report from scratch.

---

## Model summary

**Process flow**

```
Arrivals (Poisson) → [CASHIER queue] → order+pay → [KITCHEN queue]
      → cook → [PICKUP queue] → hand-off → depart
```

**Baseline parameters** (see `config.py`)

| Element | Distribution | Value |
|---|---|---|
| Inter-arrival time | Exponential | rate 0.75/min (45/hr) |
| Cashier service | Exponential | mean 1.5 min |
| Kitchen service | Triangular | (2.0, 3.0, 5.0) min |
| Pickup service | Exponential | mean 0.5 min |
| Cashiers / Kitchen / Pickup | — | 2 / 3 / 1 servers |
| Warm-up / Run length | — | 60 min / 480 min |
| Replications | — | 30 (independent seeds) |

**What-if scenarios:** baseline, peak demand (60/hr), peak + extra cashier,
peak + extra kitchen, peak + both.

---

## Key findings

- The **kitchen is the bottleneck**. At baseline it runs at ~83% utilization,
  the highest of the three stages.
- At **peak demand** the kitchen saturates (~99%) and average time in system
  more than quadruples.
- Adding a **cashier does not help** — the cashier was never the constraint.
- Adding **one kitchen station** restores near-baseline service, cutting
  average time in system by ~73%.

**Verification & validation:** the simplified single-server configuration
reproduces the analytic M/M/1 results (Wq, W, L, P(wait), utilization) to
within the simulated 95% confidence intervals, and Little's Law holds to
within ~3% for all stable scenarios.

---

## Reproducibility

All randomness is seeded through NumPy generators derived from a master seed
in `config.py` (`base_seed`). Each replication uses a distinct, independent
stream, so rerunning any command reproduces the reported numbers exactly.
