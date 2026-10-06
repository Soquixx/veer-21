from .baseline import greedy_plan
from .objective import PRESETS, Weights, finalize, plan_value, score_plan


def __getattr__(name):            # OR-Tools is only imported when the solver is actually used
    if name in ("solve", "solve_initial"):
        from . import solver
        return getattr(solver, name)
    raise AttributeError(name)
