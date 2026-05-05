from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter()

# src/ is already on sys.path (added by app.py)
_SCENARIOS_DIR = Path(__file__).resolve().parent.parent.parent / "test" / "benchmark" / "scenarios"


def _benchmark_dir() -> Path:
    from config.storage import StorageConfig
    return Path(StorageConfig().benchmark_dir)


def _report_path() -> Path:
    return _benchmark_dir() / "report.json"


def _history_path() -> Path:
    return _benchmark_dir() / "history.json"


@router.get("/api/benchmark/scenarios")
def benchmark_scenarios():
    if not _SCENARIOS_DIR.exists():
        return {"scenarios": []}
    names = sorted(p.stem for p in _SCENARIOS_DIR.glob("*.yaml"))
    return {"scenarios": names}


@router.get("/api/benchmark/report")
def benchmark_report():
    p = _report_path()
    if not p.exists():
        return {"results": []}
    return {"results": json.loads(p.read_text(encoding="utf-8"))}


@router.get("/api/benchmark/history")
def benchmark_history():
    p = _history_path()
    if not p.exists():
        return {"history": []}
    return {"history": json.loads(p.read_text(encoding="utf-8"))}


@router.post("/api/benchmark/run")
def benchmark_run(body: dict):
    selected: list[str] | None = body.get("scenarios")

    def _stream():
        from test.benchmark.runner import ScenarioRunner
        from test.benchmark.scenarios.base import ScenarioLoader
        from test.benchmark.reporter import save_report
        from test.benchmark.drift import append_history

        if not _SCENARIOS_DIR.exists():
            yield "data: " + json.dumps({"error": "No scenarios found"}) + "\n\n"
            return

        all_scenarios = ScenarioLoader.load_all(_SCENARIOS_DIR)
        if selected:
            scenarios = [s for s in all_scenarios if s.name in selected]
        else:
            scenarios = all_scenarios

        results = []
        for scenario in scenarios:
            runner = ScenarioRunner(scenario)
            result, _answer = runner.run()
            result_dict = asdict(result)
            results.append(result_dict)
            yield "data: " + json.dumps({"scenario": scenario.name, "result": result_dict}) + "\n\n"

        out_dir = _benchmark_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        report_p = _report_path()
        report_p.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        append_history(_history_path(), results)
        yield "data: " + json.dumps({"done": True, "total": len(results)}) + "\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/api/benchmark/report")
def benchmark_clear():
    deleted = []
    for p in [_report_path(), _history_path()]:
        if p.exists():
            p.unlink()
            deleted.append(p.name)
    return {"deleted": deleted}
