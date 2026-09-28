"""
config.py
=========
Central configuration for the fast-food discrete-event simulation.

All model parameters live here so that the simulation engine (simulation.py)
contains no "magic numbers".  Each scenario is a plain dictionary that
overrides one or more baseline parameters, which makes the what-if analysis
in analysis.py a simple loop over a list of configurations.

Time unit throughout the project: MINUTES.

ISYE 6644 - Topic 5: Fast Food Simulation
Team: Nahom Sososa, Neil Shukla
"""

from copy import deepcopy

# ---------------------------------------------------------------------------
# Baseline model parameters
# ---------------------------------------------------------------------------
# The baseline represents a single fast-food restaurant during a busy but
# stable lunch service.  Arrivals follow a Poisson process; service stages
# use a mix of exponential and triangular distributions (see input modeling
# section of the report).
BASELINE = {
    "name": "Baseline",

    # --- Arrival process --------------------------------------------------
    # Poisson arrivals => exponential inter-arrival times.
    # arrival_rate is lambda in customers per minute.
    "arrival_rate": 0.75,          # 0.75/min = 45 customers/hour

    # --- Resource capacities (number of parallel servers) -----------------
    "num_cashiers": 2,             # order-taking / payment stations
    "num_kitchen": 3,              # food-preparation stations (cooks)
    "num_pickup": 1,               # order hand-off counters

    # --- Service-time distributions --------------------------------------
    # Each entry is (distribution_name, parameter_dict).
    # Supported: "expon"     -> {"mean": m}
    #            "triangular" -> {"low": a, "mode": c, "high": b}
    "order_service": ("expon", {"mean": 1.5}),                 # cashier
    "kitchen_service": ("triangular", {"low": 2.0,
                                       "mode": 3.0,
                                       "high": 5.0}),          # kitchen (mean 3.333)
    "pickup_service": ("expon", {"mean": 0.5}),                # pickup counter

    # --- Run control ------------------------------------------------------
    "sim_time": 480.0,             # length of one run in minutes (8-hour day)
    "warmup_time": 60.0,          # initial transient discarded (minutes)
    "num_replications": 30,        # independent replications per scenario
    "base_seed": 12345,            # master seed; each rep derives its own seed
}


# ---------------------------------------------------------------------------
# What-if scenarios
# ---------------------------------------------------------------------------
# Every scenario starts from a copy of BASELINE and overrides selected keys.
def _make(name, **overrides):
    cfg = deepcopy(BASELINE)
    cfg["name"] = name
    cfg.update(overrides)
    return cfg


SCENARIOS = [
    # 1. Baseline reference case.
    deepcopy(BASELINE),

    # 2. Peak demand: arrival rate rises from 45/hr to 60/hr.  The kitchen
    #    (baseline bottleneck) is pushed past capacity.
    _make("Peak demand (60/hr)", arrival_rate=1.0),

    # 3. Peak demand + one extra cashier.  Tests whether front-of-house
    #    staffing relieves the congestion (it should not - cashier is not
    #    the bottleneck).
    _make("Peak + extra cashier", arrival_rate=1.0, num_cashiers=3),

    # 4. Peak demand + one extra kitchen station.  Targets the true
    #    bottleneck.
    _make("Peak + extra kitchen", arrival_rate=1.0, num_kitchen=4),

    # 5. Peak demand + extra cashier AND extra kitchen station.
    _make("Peak + cashier + kitchen",
          arrival_rate=1.0, num_cashiers=3, num_kitchen=4),
]


# ---------------------------------------------------------------------------
# Validation configuration (used by simulation.py --validate)
# ---------------------------------------------------------------------------
# A deliberately simplified single-server, exponential-service configuration
# whose behaviour can be checked against the closed-form M/M/1 queue.
VALIDATION = {
    "name": "M/M/1 validation",
    "arrival_rate": 0.60,          # lambda
    "service_rate": 1.00,          # mu  (=> rho = 0.6)
    "sim_time": 20000.0,
    "warmup_time": 1000.0,
    "num_replications": 20,
    "base_seed": 999,
}
