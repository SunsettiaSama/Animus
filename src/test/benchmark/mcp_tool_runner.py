"""
MCPToolRunner — smoke-gate BenchmarkRunner that enumerates registered MCP tools
and validates their schemas.

If no MCP server is configured, the runner skips all cases gracefully and
returns an empty result list (no failures).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from test.benchmark.metrics import MetricsCollector, ScenarioResult

_SRC = Path(__file__).resolve().parent.parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _load_mcp_registry():
    from agent.react.action.mcp.registry import MCPRegistry
    registry = MCPRegistry()
    registry.load_all()
    return registry


def _run_tool_case(tool_name: str, schema: dict) -> ScenarioResult:
    collector = MetricsCollector(f"mcp_{tool_name}")
    collector.mark_step(0)
    t0 = time.perf_counter()

    steps: list[dict] = []
    ok = True
    error_msg: str | None = None

    # Schema validation
    required_keys = {"name", "description"}
    missing = required_keys - set(schema.keys())
    if missing:
        ok = False
        error_msg = f"Schema missing required keys: {missing}"
        steps.append({"step": "schema_check", "status": "fail", "missing": list(missing)})
    else:
        steps.append({"step": "schema_check", "status": "ok", "description": schema.get("description", "")[:100]})

    # Parameters schema check (if present)
    params = schema.get("parameters") or schema.get("inputSchema") or {}
    if params:
        steps.append({"step": "params_schema", "status": "ok", "type": params.get("type", "unknown")})
    else:
        steps.append({"step": "params_schema", "status": "warn", "note": "no parameters schema"})

    wall_ms = (time.perf_counter() - t0) * 1000

    if ok:
        collector.mark_done("schema valid")
    else:
        collector.mark_failed("assertion", error=error_msg)

    result = collector.finalize(quality_score=1.0 if ok else 0.0)
    result.trace = {
        "input":      {"tool_name": tool_name},
        "steps":      steps,
        "output":     schema.get("description", "")[:200],
        "elapsed_ms": round(wall_ms, 3),
    }
    return result


class MCPToolRunner:
    """
    BenchmarkRunner that enumerates registered MCP tools and validates schemas.

    Gate: smoke — validates tool schema structure only, no actual MCP server calls.
    If no MCP server is configured, returns an empty list (no failures).
    """

    name = "mcp_tool"
    gate = "smoke"

    def run_all(self) -> list[ScenarioResult]:
        registry = _load_mcp_registry()
        tools = registry.list_tools() if hasattr(registry, "list_tools") else []
        if not tools:
            return []

        results: list[ScenarioResult] = []
        for tool in tools:
            name = tool.get("name", "unknown")
            results.append(_run_tool_case(name, tool))
        return results

    def describe(self) -> str:
        count = 0
        registry = _load_mcp_registry()
        if hasattr(registry, "list_tools"):
            count = len(registry.list_tools())
        return f"{count} MCP tool(s) — schema validation only"
