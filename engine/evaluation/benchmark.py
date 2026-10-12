"""Reproducible benchmark.  python -m engine.evaluation.benchmark --sizes S M --seeds 10

Initial planning : greedy priority-first  vs  CP-SAT
Replanning       : greedy patch-by-hand | CP-SAT re-solve from scratch | CP-SAT min-churn
All plans start from the SAME CP-SAT baseline plan and face the SAME disruption, and every
result is checked by the independent validator."""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from statistics import mean
from time import perf_counter

from ..constraints.feasibility import validate
from ..data.generator import EVENT_KINDS, generate, make_event
from ..optimization.baseline import greedy_plan
from ..replanning.replan import patch_by_hand, replan, resolve_from_scratch

METHODS = ("patch", "scratch", "minchurn")


def run_case(size: str, tightness: float, seed: int, *, trap_groups: int = 0,
             kind: str = "aircraft_out", time_limit: float = 10.0,
             workers: int | None = None, replan_limit: float = 5.0) -> dict:
    from ..optimization.solver import solve

    state = generate(size, tightness, seed, trap_groups)
    t = perf_counter()
    g = greedy_plan(state)
    g_ms = (perf_counter() - t) * 1000
    o = solve(state, hint=g, time_limit=time_limit, workers=workers, seed=seed)

    ev = make_event(state, o, kind, seed)
    res = {
        "patch": patch_by_hand(state, o, ev),
        "scratch": resolve_from_scratch(state, o, ev, time_limit=time_limit, workers=workers, seed=seed),
        "minchurn": replan(state, o, ev, time_limit=replan_limit, workers=workers, seed=seed),
    }
    row = {
        "size": size, "tightness": tightness, "seed": seed, "event": kind, "traps": trap_groups,
        "missions": len(state.missions),
        "greedy_n": len(g.assignments), "greedy_value": g.value, "greedy_ms": round(g_ms, 1),
        "greedy_viol": len(validate(g, state)),
        "opt_n": len(o.assignments), "opt_value": o.value, "opt_ms": round(o.solve_ms, 1),
        "opt_status": o.status, "opt_viol": len(o.violations),
        "opt_gap_pct": round(100 * max(0.0, o.meta["bound"] - o.meta["objective"])
                             / max(1.0, abs(o.meta["objective"])), 2) if "bound" in o.meta else 0.0,
        "affected": len(res["patch"].impact.directly_affected),
    }
    for k, r in res.items():
        row[f"{k}_retained"] = round(100 * r.metrics.value_retained, 2)
        row[f"{k}_changed"] = r.metrics.sorties_changed
        row[f"{k}_ms"] = round(r.metrics.solve_ms, 1)
        row[f"{k}_viol"] = r.metrics.violations
        row[f"{k}_status"] = r.plan.status
    return row


def run_benchmark(sizes, tightness, seeds, kinds=("aircraft_out",), trap_groups=0,
                  time_limit: float = 10.0, workers: int | None = None, verbose: bool = True,
                  replan_limit: float = 5.0) -> list[dict]:
    rows = []
    for size in sizes:
        for tg in tightness:
            for kind in kinds:
                for seed in seeds:
                    rows.append(run_case(size, tg, seed, trap_groups=trap_groups, kind=kind,
                                         time_limit=time_limit, workers=workers, replan_limit=replan_limit))
                    if verbose:
                        r = rows[-1]
                        print(f"[{size} t={tg} {kind} seed={seed}] greedy {r['greedy_value']} -> "
                              f"opt {r['opt_value']} | changed patch/scratch/min-churn = "
                              f"{r['patch_changed']}/{r['scratch_changed']}/{r['minchurn_changed']}", flush=True)
    return rows


def summarize(rows: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for r in rows:
        groups[(r["size"], r["tightness"], r["event"], r["traps"])].append(r)
    out = []
    for (size, tg, ev, traps), rs in groups.items():
        row = {"size": size, "tightness": tg, "event": ev, "traps": traps, "runs": len(rs)}
        for key in rs[0]:
            if key in ("size", "tightness", "seed", "event", "traps", "opt_status") or key.endswith("_status"):
                continue
            row[key] = round(mean(r[key] for r in rs), 2)
        row["fallbacks"] = sum(1 for r in rs for m in ("scratch", "minchurn")
                               if any(k in r[m + "_status"] for k in ("INFEAS", "UNKNOWN", "INVALID")))
        row["violations_total"] = sum(r["greedy_viol"] + r["opt_viol"] + sum(r[f"{m}_viol"] for m in METHODS)
                                      for r in rs)
        out.append(row)
    return out


def to_markdown(summary: list[dict]) -> str:
    a = ["| size | tight | traps | missions | greedy flown / value / ms | CP-SAT flown / value / ms | gain | gap % |",
         "|---|---|---|---|---|---|---|---|"]
    b = ["| size | tight | event | affected | method | value retained % | sorties changed | ms |",
         "|---|---|---|---|---|---|---|---|"]
    seen = set()
    for s in summary:
        key = (s["size"], s["tightness"], s["traps"])
        if key not in seen:                              # same instances across events: show once
            seen.add(key)
            gain = 100 * (s["opt_value"] / max(1, s["greedy_value"]) - 1)
            a.append(f"| {s['size']} | {s['tightness']} | {s['traps']} | {s['missions']} | "
                     f"{s['greedy_n']} / {s['greedy_value']} / {s['greedy_ms']} | "
                     f"{s['opt_n']} / {s['opt_value']} / {s['opt_ms']} | +{gain:.1f}% | {s['opt_gap_pct']} |")
        for m, name in (("patch", "greedy patch"), ("scratch", "re-solve scratch"), ("minchurn", "**min-churn**")):
            b.append(f"| {s['size']} | {s['tightness']} | {s['event']} | {s['affected']} | {name} | "
                     f"{s[m + '_retained']} | {s[m + '_changed']} | {s[m + '_ms']} |")
    v = sum(s["violations_total"] for s in summary)
    fb = sum(s["fallbacks"] for s in summary)
    return ("### Initial planning\n" + "\n".join(a) + "\n\n### Replanning after disruption\n" + "\n".join(b)
            + f"\n\nValidator violations across all plans: **{v}** | solver fallbacks/infeasible runs: **{fb}**\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sizes", nargs="+", default=["S", "M"])
    ap.add_argument("--tightness", nargs="+", type=float, default=[0.9])
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--events", nargs="+", default=["aircraft_out"], choices=EVENT_KINDS)
    ap.add_argument("--traps", type=int, default=0, help="trap groups per instance")
    ap.add_argument("--time-limit", type=float, default=10.0)
    ap.add_argument("--replan-time-limit", type=float, default=5.0,
                    help="time budget for the min-churn replan (initial plan and re-solve baseline use --time-limit)")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--out", default="benchmark_results.csv")
    args = ap.parse_args()
    rows = run_benchmark(args.sizes, args.tightness, range(args.seeds), args.events, args.traps,
                         args.time_limit, args.workers, replan_limit=args.replan_time_limit)
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print("\n" + to_markdown(summarize(rows)))
    print(f"raw rows -> {args.out}")


if __name__ == "__main__":
    main()
