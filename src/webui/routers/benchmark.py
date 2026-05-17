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


# ── Scenario metadata ─────────────────────────────────────────────────────────

@router.get("/api/benchmark/scenarios/{name}")
def benchmark_scenario_detail(name: str):
    """
    Return full metadata for a single scenario: YAML content + last run result.

    For YAML-based scenarios, returns full spec + last result.
    For atomic-tool / skill / MCP scenarios without a YAML file, returns
    just the last result from the saved report with a minimal spec stub.

    Response shape:
      name, description, prompt, expected, thresholds,
      llm_script_count, tool_names, delay_ms, ttfb_ms,
      last_result: { ...ScenarioResult fields } | null
    """
    last_result = None
    p = _report_path()
    if p.exists():
        records = json.loads(p.read_text(encoding="utf-8"))
        for r in records:
            if r.get("scenario") == name:
                last_result = r
                break

    yaml_path = _SCENARIOS_DIR / f"{name}.yaml"
    if yaml_path.exists():
        from test.benchmark.scenarios.base import ScenarioLoader
        scenario = ScenarioLoader.load(yaml_path)
        return {
            "name": scenario.name,
            "description": scenario.description,
            "prompt": scenario.prompt,
            "expected": scenario.expected,
            "thresholds": scenario.thresholds,
            "llm_script_count": len(scenario.llm_script),
            "tool_names": sorted(scenario.tool_script.keys()),
            "delay_ms": scenario.delay_ms,
            "ttfb_ms": scenario.ttfb_ms,
            "last_result": last_result,
        }

    # Non-YAML scenario: return result-only stub
    if last_result is None:
        return JSONResponse(status_code=404, content={"error": f"Scenario {name!r} not found"})

    trace = last_result.get("trace") or {}
    return {
        "name":             name,
        "description":      trace.get("output", ""),
        "prompt":           json.dumps(trace.get("input", {}), ensure_ascii=False),
        "expected":         {},
        "thresholds":       {},
        "llm_script_count": 0,
        "tool_names":       [trace.get("tool", "")] if trace.get("tool") else [],
        "delay_ms":         0,
        "ttfb_ms":          0,
        "last_result":      last_result,
    }


# ── Existing mock-benchmark endpoints ─────────────────────────────────────────

@router.get("/api/benchmark/scenarios")
def benchmark_scenarios():
    names: list[str] = []
    if _SCENARIOS_DIR.exists():
        names.extend(p.stem for p in _SCENARIOS_DIR.glob("*.yaml"))
    # Include any non-YAML scenarios that appear in the latest report
    p = _report_path()
    if p.exists():
        records = json.loads(p.read_text(encoding="utf-8"))
        existing = set(names)
        for r in records:
            sname = r.get("scenario", "")
            if sname and sname not in existing:
                names.append(sname)
                existing.add(sname)
    return {"scenarios": sorted(names)}


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
        result_objs = []
        for scenario in scenarios:
            runner = ScenarioRunner(scenario)
            result, _answer = runner.run()
            result_objs.append(result)
            result_dict = asdict(result)
            results.append(result_dict)
            yield "data: " + json.dumps({"scenario": scenario.name, "result": result_dict}) + "\n\n"

        out_dir = _benchmark_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        save_report(result_objs, _report_path())
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


# ── BenchmarkSuite gate-aware runner ──────────────────────────────────────────

@router.post("/api/benchmark/run-suite")
def benchmark_run_suite(body: dict):
    """
    Run the full BenchmarkSuite (all registered runners) or a single gate level.

    Body:
      gate:           "smoke" | "regression" | "performance" | "all"  (default: "all")
      fail_on_drift:  bool  (default: false)
    """
    gate_param: str = body.get("gate", "all")
    fail_on_drift: bool = bool(body.get("fail_on_drift", False))

    def _stream():
        from dataclasses import asdict

        from test.benchmark.runner import ScenarioFileRunner
        from test.benchmark.suite import BenchmarkSuite

        suite = BenchmarkSuite()
        suite.register(ScenarioFileRunner(_SCENARIOS_DIR))

        try:
            from test.benchmark.atomic_tool_runner import AtomicToolRunner
            suite.register(AtomicToolRunner())
        except ImportError:
            pass

        try:
            from test.benchmark.skill_runner import SkillRunner
            suite.register(SkillRunner())
        except (ImportError, OSError):
            pass

        try:
            from test.benchmark.mcp_tool_runner import MCPToolRunner
            suite.register(MCPToolRunner())
        except (ImportError, OSError):
            pass

        try:
            from test.benchmark.dag_runner import DagOrchestratorRunner
            suite.register(DagOrchestratorRunner())
        except (ImportError, OSError):
            pass

        gate = None if gate_param == "all" else gate_param
        try:
            report = suite.run(gate=gate)
        except ValueError as exc:
            yield "data: " + json.dumps({"error": str(exc)}) + "\n\n"
            return

        # Stream per-runner results
        for runner_name, results in report.runner_results.items():
            for r in results:
                yield "data: " + json.dumps({
                    "runner": runner_name,
                    "scenario": r.scenario,
                    "result": asdict(r),
                }) + "\n\n"

        # Drift detection
        alerts = suite.check_drift(report, _history_path())
        alert_strs = [str(a) for a in alerts]

        # Save report
        out_dir = _benchmark_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        suite.save(report, _report_path())

        yield "data: " + json.dumps({
            "done": True,
            "total": report.total_scenarios,
            "passed": report.passed,
            "failed": report.failed,
            "pass_rate": report.pass_rate,
            "gate": gate_param,
            "drift_alerts": alert_strs,
            "has_drift": report.has_drift,
        }) + "\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Metric trend — reads history and returns per-scenario time-series ─────────

@router.get("/api/benchmark/metrics/trend")
def benchmark_metrics_trend(metric: str = "wall_ms", scenario: str = ""):
    """
    Return a per-scenario time-series for a single metric, read from history.json.

    Query params:
      metric:   one of  wall_ms | total_tokens | quality_score | retry_rate
                        total_prompt_tokens | total_completion_tokens | steps | llm_retries
      scenario: optional filter — when set, return only that scenario's series

    Response:
      {
        "metric": "wall_ms",
        "series": {
          "scenario_name": [
            {"run_at": "2026-05-06T...", "value": 123.4},
            ...
          ]
        }
      }
    """
    p = _history_path()
    if not p.exists():
        return {"metric": metric, "series": {}}

    history: list[dict] = json.loads(p.read_text(encoding="utf-8"))
    series: dict[str, list[dict]] = {}

    def _extract(r: dict, m: str) -> float | None:
        if m == "total_tokens":
            return r.get("total_prompt_tokens", 0) + r.get("total_completion_tokens", 0)
        if m == "retry_rate":
            retries = r.get("llm_retries", 0)
            steps = max(r.get("steps", 1), 1)
            return retries / steps
        v = r.get(m)
        if v is None:
            return None
        return float(v)

    for run in history:
        run_at: str = run.get("run_at", "")
        for r in run.get("results", []):
            sname: str = r.get("scenario", "")
            if scenario and sname != scenario:
                continue
            val = _extract(r, metric)
            if val is None:
                continue
            if sname not in series:
                series[sname] = []
            series[sname].append({"run_at": run_at, "value": val})

    return {"metric": metric, "series": series}


# ── Live benchmark (real TaoLoop + obs instrumentation) ───────────────────────

@router.post("/api/benchmark/run-live")
def benchmark_run_live(body: dict):
    selected: list[str] | None = body.get("scenarios")

    def _stream():
        from state import get_state
        from test.benchmark.scenarios.base import ScenarioLoader
        from test.obs.live_runner import LiveScenarioRunner

        state = get_state()

        if state.active_tao is None:
            yield "data: " + json.dumps({"error": "Agent not initialized. Configure LLM first."}) + "\n\n"
            return

        if state.is_streaming:
            yield "data: " + json.dumps({"error": "Agent is currently streaming a conversation."}) + "\n\n"
            return

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
            runner = LiveScenarioRunner(scenario, state.active_tao)
            result, _answer = runner.run()
            result_dict = asdict(result)
            results.append(result_dict)
            yield "data: " + json.dumps({"scenario": scenario.name, "result": result_dict, "live": True}) + "\n\n"

        out_dir = _benchmark_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        live_report_p = out_dir / "live_report.json"
        live_report_p.write_text(
            json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        yield "data: " + json.dumps({"done": True, "total": len(results), "live": True}) + "\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Obs stats & session inspection ────────────────────────────────────────────

@router.get("/api/benchmark/obs/stats")
def obs_stats():
    from test.obs.collector import get_collector
    events = get_collector().read_today()

    llm_events = [e for e in events if e.get("kind") == "LLMCallEvent"]
    tool_events = [e for e in events if e.get("kind") == "ToolCallEvent"]
    session_starts = [e for e in events if e.get("kind") == "SessionEvent" and e.get("event_type") == "start"]

    total_prompt = sum(e.get("prompt_tokens", 0) for e in llm_events)
    total_completion = sum(e.get("completion_tokens", 0) for e in llm_events)
    latencies = sorted(e.get("latency_ms", 0.0) for e in llm_events)

    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    p95_idx = max(0, int(len(latencies) * 0.95) - 1)
    p95_latency = latencies[p95_idx] if latencies else 0.0

    tool_dist: dict[str, int] = {}
    for e in tool_events:
        name = e.get("tool_name", "unknown")
        tool_dist[name] = tool_dist.get(name, 0) + 1

    api_calls = sum(1 for e in llm_events if e.get("token_source") == "api")
    estimated_calls = len(llm_events) - api_calls

    return {
        "total_llm_calls": len(llm_events),
        "api_token_calls": api_calls,
        "estimated_token_calls": estimated_calls,
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_tokens": total_prompt + total_completion,
        "avg_latency_ms": round(avg_latency, 1),
        "p95_latency_ms": round(p95_latency, 1),
        "total_tool_calls": len(tool_events),
        "tool_distribution": tool_dist,
        "total_sessions": len(session_starts),
    }


@router.get("/api/benchmark/obs/sessions")
def obs_sessions():
    from test.obs.collector import get_collector
    events = get_collector().read_today()

    sessions: dict[str, dict] = {}
    for ev in events:
        sid = ev.get("session_id", "")
        if not sid:
            continue
        if sid not in sessions:
            sessions[sid] = {
                "session_id": sid,
                "question_summary": "",
                "total_steps": 0,
                "total_tokens": 0,
                "wall_ms": 0.0,
                "status": "running",
                "ts": ev.get("ts", 0.0),
                "llm_calls": 0,
                "tool_calls": 0,
            }

        kind = ev.get("kind")
        if kind == "SessionEvent":
            et = ev.get("event_type")
            if et == "start":
                sessions[sid]["question_summary"] = ev.get("question_summary", "")
                sessions[sid]["ts"] = ev.get("ts", 0.0)
            elif et in ("finish", "max_steps"):
                sessions[sid]["total_steps"] = ev.get("total_steps", 0)
                sessions[sid]["status"] = et
                start_ts = sessions[sid]["ts"]
                end_ts = ev.get("ts", 0.0)
                if start_ts:
                    sessions[sid]["wall_ms"] = round((end_ts - start_ts) * 1000, 1)
        elif kind == "LLMCallEvent":
            sessions[sid]["total_tokens"] += (
                ev.get("prompt_tokens", 0) + ev.get("completion_tokens", 0)
            )
            sessions[sid]["llm_calls"] += 1
        elif kind == "ToolCallEvent":
            sessions[sid]["tool_calls"] += 1

    session_list = sorted(sessions.values(), key=lambda x: x["ts"], reverse=True)[:20]
    return {"sessions": session_list}


@router.get("/api/benchmark/obs/session/{session_id}")
def obs_session_detail(session_id: str):
    from test.obs.collector import get_collector
    events = get_collector().read_session(session_id)
    events_sorted = sorted(events, key=lambda x: x.get("ts", 0.0))
    return {"session_id": session_id, "events": events_sorted}
