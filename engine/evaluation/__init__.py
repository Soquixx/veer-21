def __getattr__(name):
    if name in ("run_benchmark", "run_case", "summarize", "to_markdown"):
        from . import benchmark
        return getattr(benchmark, name)
    raise AttributeError(name)
