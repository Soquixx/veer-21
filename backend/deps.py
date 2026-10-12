from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException, Request


def get_jobs(request: Request):
    jobs = getattr(request.app.state, "jobs", None)
    if jobs is None:
        raise HTTPException(503, "job manager is not running")
    return jobs


def engine_call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Bad event ids / malformed JSON are the caller's fault (422), not a server error (500)."""
    try:
        return fn(*args, **kwargs)
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(422, f"engine rejected the input: {type(exc).__name__}: {exc}")
