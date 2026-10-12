# veer-21
# AirOps engine

    pip install -r requirements.txt
    python -m engine.demo --size M --tightness 0.9 --seed 7 --traps 2
    python -m engine.evaluation.benchmark --sizes S M --tightness 0.9 1.1 --seeds 10 --traps 1
    pytest engine/tests

Layout: domain (models) -> data (seeded generator + events) -> constraints (pruning + independent
validator) -> optimization (greedy baseline, CP-SAT model, solver) -> replanning (events, impact,
min-churn replan, plan A/B/C) -> resilience (Monte Carlo stress test) -> evaluation (benchmark).
Models are stdlib dataclasses; FastAPI accepts them directly. Use to_dict / from_dict for JSON.
