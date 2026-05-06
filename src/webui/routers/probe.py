"""
WebUI router — /api/probe/*

Exposes the in-process probe ring-buffer to the frontend.
No authentication, no persistence — this is a developer tool.
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/api/probe/runs")
def probe_runs(limit: int = 100, tag: str = "", name: str = ""):
    """
    List recent probe runs, newest first.

    Query params:
      limit  max number of runs to return (default 100)
      tag    filter by tag (exact match, optional)
      name   filter by probe name prefix (optional)
    """
    from test.probe import get_runs
    runs = get_runs(limit=500)   # fetch generously, filter in Python
    if tag:
        runs = [r for r in runs if tag in r.tags]
    if name:
        runs = [r for r in runs if r.probe_name.startswith(name)]
    return {"runs": [asdict(r) for r in runs[:limit]]}


@router.get("/api/probe/runs/{run_id}")
def probe_run_detail(run_id: str):
    """Return a single probe run by run_id."""
    from test.probe import get_runs
    for r in get_runs(limit=500):
        if r.run_id == run_id:
            return asdict(r)
    return JSONResponse(status_code=404, content={"error": f"Run {run_id!r} not found"})


@router.delete("/api/probe/runs")
def probe_clear():
    """Clear all probe runs from the in-process ring buffer."""
    from test.probe import clear_runs
    clear_runs()
    return {"ok": True}


@router.get("/api/probe/tags")
def probe_tags():
    """Return all unique tags seen across stored runs."""
    from test.probe import get_runs
    tags: set[str] = set()
    for r in get_runs(limit=500):
        tags.update(r.tags)
    return {"tags": sorted(tags)}
