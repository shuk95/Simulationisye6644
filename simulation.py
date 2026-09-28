"""
simulation.py
=============
Discrete-event simulation of a fast-food restaurant built with SimPy.

Model overview
--------------
A customer flows through three service stages, each backed by a limited
SimPy resource:

    arrive --> [CASHIER queue] --> order --> [KITCHEN queue] --> cook
           --> [PICKUP queue] --> hand-off --> depart

The module provides:
  * FastFoodSim   - one independent simulation run + statistics collection
  * run_scenario  - runs N replications of a scenario and returns a DataFrame
  * validate      - compares a simplified model against analytic M/M/1 results

Run from the command line:
    python simulation.py --scenario baseline      # single scenario summary
    python simulation.py --validate               # V&V against M/M/1
    python simulation.py                          # baseline (default)

ISYE 6644 - Topic 5: Fast Food Simulation
Team: Nahom Sososa, Neil Shukla
"""

import argparse
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import simpy

try:
    from . import config
except ImportError:              # allow running as a plain script
    import config


# ===========================================================================
# Random variate generation
# ===========================================================================
def make_service_sampler(dist_spec, rng):
    """Return a zero-argument function that draws one service time.

    dist_spec is a (name, params) tuple as defined in config.py.  A dedicated
    numpy Generator (rng) is passed in so that every stream is reproducible
    and independent across replications.
    """
    name, params = dist_spec
    if name == "expon":
        mean = params["mean"]
        return lambda: rng.exponential(mean)
    if name == "triangular":
        return lambda: rng.triangular(params["low"], params["mode"],
                                      params["high"])
    if name == "constant":
        val = params["value"]
        return lambda: val
    raise ValueError(f"Unknown distribution: {name!r}")


# ===========================================================================
# Per-run statistics container
# ===========================================================================
@dataclass
class Stats:
    """Collects observations for a single simulation run.

    Only customers who *arrive* after the warm-up cutoff are recorded, which
    removes the initial transient from every average.  Resource-busy area is
    also accumulated only over the post-warmup window so utilisation is a
    steady-state estimate.
    """
    warmup: float
    sim_time: float

    # per-customer observations (post-warmup arrivals only)
    wait_cashier: list = field(default_factory=list)
    wait_kitchen: list = field(default_factory=list)
    wait_pickup: list = field(default_factory=list)
    time_in_system: list = field(default_factory=list)
    waited_for_cashier: list = field(default_factory=list)  # 1 if queued, else 0

    num_served: int = 0

    # time-average area accumulators (number in system)
    _area_n: float = 0.0
    _last_t: float = None
    _n_in_system: int = 0

    # resource busy-time area accumulators, keyed by stage name
    busy_area: dict = field(default_factory=lambda: {"cashier": 0.0,
                                                     "kitchen": 0.0,
                                                     "pickup": 0.0})

    def start_clock(self, t):
        self._last_t = t

    # --- number-in-system tracking (area under the L(t) curve) ------------
    def _accumulate_area(self, t):
        if self._last_t is not None and t > self._last_t:
            if t > self.warmup:            # only count post-warmup area
                lo = max(self._last_t, self.warmup)
                self._area_n += self._n_in_system * (t - lo)
        self._last_t = t

    def customer_enter(self, t):
        self._accumulate_area(t)
        self._n_in_system += 1

    def customer_leave(self, t):
        self._accumulate_area(t)
        self._n_in_system -= 1

    # --- summarise into a flat dict of scalar metrics ---------------------
    def summary(self, cfg):
        obs_window = self.sim_time - self.warmup
        caps = {"cashier": cfg["num_cashiers"],
                "kitchen": cfg["num_kitchen"],
                "pickup": cfg["num_pickup"]}

        def mean(x):
            return float(np.mean(x)) if x else float("nan")

        util = {stage: self.busy_area[stage] / (obs_window * caps[stage])
                for stage in caps}

        L = self._area_n / obs_window            # time-avg number in system
        W = mean(self.time_in_system)            # avg time in system
        throughput_hr = self.num_served / obs_window * 60.0

        return {
            "avg_wait_cashier": mean(self.wait_cashier),
            "avg_wait_kitchen": mean(self.wait_kitchen),
            "avg_wait_pickup": mean(self.wait_pickup),
            "avg_time_in_system": W,
            "avg_num_in_system": L,
            "p_wait_cashier": mean(self.waited_for_cashier),
            "throughput_per_hr": throughput_hr,
            "util_cashier": util["cashier"],
            "util_kitchen": util["kitchen"],
            "util_pickup": util["pickup"],
            "num_served": self.num_served,
        }


# ===========================================================================
# The simulation model
# ===========================================================================
class FastFoodSim:
    """A single independent replication of the fast-food restaurant."""

    def __init__(self, cfg, seed):
        self.cfg = cfg
        self.rng = np.random.default_rng(seed)
        self.env = simpy.Environment()

        # Shared resources (parallel servers).
        self.cashier = simpy.Resource(self.env, capacity=cfg["num_cashiers"])
        self.kitchen = simpy.Resource(self.env, capacity=cfg["num_kitchen"])
        self.pickup = simpy.Resource(self.env, capacity=cfg["num_pickup"])

        # Independent variate streams for each stage.
        self.sample_order = make_service_sampler(cfg["order_service"], self.rng)
        self.sample_kitchen = make_service_sampler(cfg["kitchen_service"], self.rng)
        self.sample_pickup = make_service_sampler(cfg["pickup_service"], self.rng)

        self.stats = Stats(warmup=cfg["warmup_time"], sim_time=cfg["sim_time"])

    # --- helper: use a resource, crediting busy time to utilisation -------
    def _serve(self, resource, stage, duration):
        """Request a server, hold it for `duration`, record busy area."""
        with resource.request() as req:
            yield req
            start = self.env.now
            yield self.env.timeout(duration)
            end = self.env.now
            # Only the portion of service that falls after warm-up counts.
            if end > self.stats.warmup:
                self.stats.busy_area[stage] += end - max(start, self.stats.warmup)

    # --- the life-cycle of one customer -----------------------------------
    def customer(self, arrive_t):
        st = self.stats
        record = arrive_t >= st.warmup      # ignore transient arrivals in per-customer stats
        st.customer_enter(self.env.now)

        # Stage 1: cashier (place order + pay) --------------------------------
        t0 = self.env.now
        with self.cashier.request() as req:
            yield req
            q_cashier = self.env.now - t0
            svc = self.sample_order()
            s0 = self.env.now
            yield self.env.timeout(svc)
            if self.env.now > st.warmup:
                st.busy_area["cashier"] += self.env.now - max(s0, st.warmup)

        # Stage 2: kitchen (food preparation) --------------------------------
        t1 = self.env.now
        with self.kitchen.request() as req:
            yield req
            q_kitchen = self.env.now - t1
            svc = self.sample_kitchen()
            s1 = self.env.now
            yield self.env.timeout(svc)
            if self.env.now > st.warmup:
                st.busy_area["kitchen"] += self.env.now - max(s1, st.warmup)

        # Stage 3: pickup (order hand-off) -----------------------------------
        t2 = self.env.now
        with self.pickup.request() as req:
            yield req
            q_pickup = self.env.now - t2
            svc = self.sample_pickup()
            s2 = self.env.now
            yield self.env.timeout(svc)
            if self.env.now > st.warmup:
                st.busy_area["pickup"] += self.env.now - max(s2, st.warmup)

        depart_t = self.env.now
        st.customer_leave(depart_t)

        if record:
            st.wait_cashier.append(q_cashier)
            st.wait_kitchen.append(q_kitchen)
            st.wait_pickup.append(q_pickup)
            st.time_in_system.append(depart_t - arrive_t)
            st.waited_for_cashier.append(1.0 if q_cashier > 1e-9 else 0.0)
            st.num_served += 1

    # --- arrival generator -------------------------------------------------
    def arrivals(self):
        rate = self.cfg["arrival_rate"]
        while True:
            yield self.env.timeout(self.rng.exponential(1.0 / rate))
            if self.env.now > self.cfg["sim_time"]:
                break
            self.env.process(self.customer(self.env.now))

    # --- run one replication ----------------------------------------------
    def run(self):
        self.stats.start_clock(0.0)
        self.env.process(self.arrivals())
        self.env.run(until=self.cfg["sim_time"])
        # close out the L(t) area at end of horizon
        self.stats._accumulate_area(self.cfg["sim_time"])
        return self.stats.summary(self.cfg)


# ===========================================================================
# Replication driver
# ===========================================================================
def run_scenario(cfg, verbose=False):
    """Run all replications of one scenario; return a per-rep DataFrame."""
    rows = []
    for r in range(cfg["num_replications"]):
        seed = cfg["base_seed"] + 1000 * r      # distinct stream per rep
        sim = FastFoodSim(cfg, seed)
        summary = sim.run()
        summary["replication"] = r + 1
        summary["scenario"] = cfg["name"]
        rows.append(summary)
        if verbose:
            print(f"  rep {r+1:>2}: Wq_cashier={summary['avg_wait_cashier']:.2f}  "
                  f"Wq_kitchen={summary['avg_wait_kitchen']:.2f}  "
                  f"W={summary['avg_time_in_system']:.2f}  "
                  f"served={summary['num_served']}")
    return pd.DataFrame(rows)


def summarize(df, alpha=0.05):
    """Collapse a per-rep DataFrame into mean +/- half-width per metric."""
    from scipy import stats as sps

    metrics = [c for c in df.columns if c not in ("replication", "scenario")]
    n = len(df)
    tcrit = sps.t.ppf(1 - alpha / 2, df=n - 1)
    out = {"scenario": df["scenario"].iloc[0], "n_reps": n}
    for m in metrics:
        vals = df[m].to_numpy(dtype=float)
        mean = vals.mean()
        sd = vals.std(ddof=1)
        hw = tcrit * sd / np.sqrt(n)
        out[f"{m}_mean"] = mean
        out[f"{m}_hw"] = hw
    return out


# ===========================================================================
# Verification & Validation: analytic M/M/1
# ===========================================================================
def validate():
    """Run a simplified M/M/1 configuration and compare to theory."""
    v = config.VALIDATION
    lam, mu = v["arrival_rate"], v["service_rate"]
    rho = lam / mu

    # Build a config the engine understands: single cashier, exponential
    # service, and instantaneous kitchen/pickup so only the M/M/1 queue acts.
    cfg = {
        "name": "MM1", "arrival_rate": lam,
        "num_cashiers": 1, "num_kitchen": 10_000, "num_pickup": 10_000,
        "order_service": ("expon", {"mean": 1.0 / mu}),
        "kitchen_service": ("constant", {"value": 0.0}),
        "pickup_service": ("constant", {"value": 0.0}),
        "sim_time": v["sim_time"], "warmup_time": v["warmup_time"],
        "num_replications": v["num_replications"], "base_seed": v["base_seed"],
    }

    df = run_scenario(cfg)
    s = summarize(df)

    # Analytic M/M/1 steady-state results.
    Wq = rho / (mu - lam)            # expected wait in queue
    W = 1.0 / (mu - lam)             # expected time in system
    L = rho / (1 - rho)             # expected number in system
    Pwait = rho                      # P(an arrival must wait) = rho

    print("\n" + "=" * 68)
    print("VERIFICATION & VALIDATION  --  M/M/1 queue")
    print(f"lambda={lam}, mu={mu}, rho={rho:.3f}, "
          f"{v['num_replications']} reps x {v['sim_time']:.0f} min")
    print("=" * 68)
    print(f"{'Metric':<22}{'Analytic':>12}{'Simulated':>14}{'95% half-w':>14}")
    print("-" * 68)
    rows = [
        ("Wq (wait in queue)", Wq, s["avg_wait_cashier_mean"], s["avg_wait_cashier_hw"]),
        ("W  (time in system)", W, s["avg_time_in_system_mean"], s["avg_time_in_system_hw"]),
        ("L  (number in sys)", L, s["avg_num_in_system_mean"], s["avg_num_in_system_hw"]),
        ("P(wait) = rho", Pwait, s["p_wait_cashier_mean"], s["p_wait_cashier_hw"]),
        ("Utilization = rho", rho, s["util_cashier_mean"], s["util_cashier_hw"]),
    ]
    for name, theo, sim, hw in rows:
        flag = "OK" if abs(theo - sim) <= hw + 0.02 * abs(theo) + 1e-6 else "??"
        print(f"{name:<22}{theo:>12.4f}{sim:>14.4f}{hw:>14.4f}   {flag}")
    print("=" * 68)
    print("OK = analytic value lies within the simulated 95% CI (allowing a")
    print("small tolerance).  Agreement across all rows validates the engine.\n")


# ===========================================================================
# Command-line entry point
# ===========================================================================
def main():
    ap = argparse.ArgumentParser(description="Fast-food DES (SimPy).")
    ap.add_argument("--scenario", default="baseline",
                    help="'baseline' or the exact name of a scenario in config.SCENARIOS")
    ap.add_argument("--validate", action="store_true",
                    help="run the M/M/1 verification & validation instead")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.validate:
        validate()
        return

    if args.scenario.lower() == "baseline":
        cfg = config.BASELINE
    else:
        matches = [c for c in config.SCENARIOS if c["name"] == args.scenario]
        if not matches:
            names = [c["name"] for c in config.SCENARIOS]
            raise SystemExit(f"Unknown scenario. Choose from: {names}")
        cfg = matches[0]

    print(f"Running scenario: {cfg['name']}  "
          f"({cfg['num_replications']} replications x {cfg['sim_time']:.0f} min)")
    df = run_scenario(cfg, verbose=args.verbose)
    s = summarize(df)

    print("\n" + "-" * 60)
    print(f"RESULTS  ({cfg['name']})   mean +/- 95% CI half-width")
    print("-" * 60)
    labels = [
        ("Avg wait for cashier (min)", "avg_wait_cashier"),
        ("Avg wait for kitchen (min)", "avg_wait_kitchen"),
        ("Avg wait for pickup (min)", "avg_wait_pickup"),
        ("Avg time in system (min)", "avg_time_in_system"),
        ("Avg number in system", "avg_num_in_system"),
        ("P(customer waits at cashier)", "p_wait_cashier"),
        ("Throughput (cust/hr)", "throughput_per_hr"),
        ("Cashier utilization", "util_cashier"),
        ("Kitchen utilization", "util_kitchen"),
        ("Pickup utilization", "util_pickup"),
    ]
    for label, key in labels:
        print(f"{label:<32}{s[key+'_mean']:>9.3f}  +/- {s[key+'_hw']:.3f}")
    print("-" * 60)


if __name__ == "__main__":
    main()
