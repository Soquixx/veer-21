"""python -m engine.demo [--size M --tightness 0.9 --seed 7 --traps 2 --event aircraft_out]
End-to-end Day-1 demo: generate -> greedy vs CP-SAT -> disruption -> three replan options."""
from __future__ import annotations

import argparse

from .data.generator import EVENT_KINDS, generate, make_event
from .optimization.baseline import greedy_plan
from .optimization.solver import solve
from .replanning.replan import patch_by_hand, replan_options, resolve_from_scratch
from .resilience.stress_test import stress_test


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default="M")
    ap.add_argument("--tightness", type=float, default=0.9)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--traps", type=int, default=0)
    ap.add_argument("--event", default="aircraft_out", choices=EVENT_KINDS)
    ap.add_argument("--time-limit", type=float, default=10.0)
    a = ap.parse_args()

    st = generate(a.size, a.tightness, a.seed, a.traps)
    print(f"Instance {a.size} tightness={a.tightness} seed={a.seed}: {len(st.aircraft)} aircraft, "
          f"{len(st.crew)} crew, {len(st.missions)} missions, horizon {st.horizon} slots")

    g = greedy_plan(st)
    o = solve(st, hint=g, time_limit=a.time_limit, seed=a.seed)
    n = len(st.missions)
    print(f"Greedy : {len(g.assignments)}/{n} missions, value {g.value}, {g.solve_ms:.0f} ms, "
          f"validator violations {len(g.violations)}")
    print(f"CP-SAT : {len(o.assignments)}/{n} missions, value {o.value}, {o.solve_ms:.0f} ms ({o.status}), "
          f"validator violations {len(o.violations)}")
    for mid in o.dropped[:5]:
        print(f"   dropped {mid}: {o.reasons.get(mid, '')}")

    ev = make_event(st, o, a.event, a.seed)
    print("\nEvent  : " + "; ".join(f"{e.type.value} {e.target_id or e.sector} @ slot {e.time}" for e in ev))
    patch = patch_by_hand(st, o, ev)
    scratch = resolve_from_scratch(st, o, ev, time_limit=a.time_limit, seed=a.seed)
    imp = patch.impact
    print(f"Impact : {len(imp.directly_affected)} sorties broken (value at risk {imp.value_at_risk}), "
          f"{len(imp.ripple)} ripple candidates")
    print(f"\n{'method':<24}{'value kept':>11}{'sorties changed':>17}{'ms':>9}")
    for r in (patch, scratch):
        m = r.metrics
        print(f"{r.label:<24}{100 * m.value_retained:>10.1f}%{m.sorties_changed:>17}{m.solve_ms:>9.0f}")
    print("\nReplan options for the commander:")
    print(f"{'plan':<18}{'value kept':>11}{'changed':>9}{'stability':>10}{'robustness':>11}{'ms':>8}  status")
    opts = replan_options(st, o, ev, time_limit=a.time_limit, seed=a.seed)
    for r in opts:
        m = r.metrics
        print(f"{r.label:<18}{100 * m.value_retained:>10.1f}%{m.sorties_changed:>9}{m.stability:>10.2f}"
              f"{m.robustness:>11.1f}{m.solve_ms:>8.0f}  {r.plan.status} violations={m.violations}")
    if len(opts) < 3:
        print(f"   ({len(opts)} distinct option(s): this disruption has no richer trade-off to offer)")
    s = stress_test(st, o, n_trials=200, seed=a.seed)
    print(f"\nStress test (200 failure draws, original plan): {100 * s.mean_retained:.1f}% value retained "
          f"with repair vs {100 * s.mean_no_repair:.1f}% without; bad-day (p10) {100 * s.p10_retained:.1f}%")


if __name__ == "__main__":
    main()
