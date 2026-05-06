"""
test/probe.py — Lightweight instrumentation decorator for the benchmark WebUI.

Design goals
────────────
1. Minimum invasion — production code is never modified.  Callers wrap
   functions at test-call-time:
       probed = probe("desc")(ToolClass().execute)
       result = probed(**args)

2. Arbitrary metrics — emit_metric(key, value) can be called from *inside*
   any probe-wrapped function (or any function it calls) using a
   contextvars.ContextVar.  No need to thread a context object around.

3. Thread & async safe — ContextVar is isolated per-coroutine / per-thread,
   so concurrent probe calls never bleed metrics into each other.

4. Zero dependencies — only stdlib (contextvars, functools, dataclasses, uuid,
   inspect, time, datetime).

Usage
─────
    from test.probe import probe, emit_metric

    # Decorate at call-site (no production code changes):
    wrapped = probe(
        description="Converts °C to °F using the standard linear formula",
        name="unit_converter.celsius_to_fahrenheit",
        tags=["unit_converter", "temperature"],
    )(UnitConverterAction().execute)

    result = wrapped(value=100.0, from_unit="C", to_unit="F")

    # Inside any function in the call-stack (e.g. in execute() itself,
    # or in a helper it calls):
    emit_metric("input_range_ok", True)
    emit_metric("conversion_factor", 1.8)
"""
from __future__ import annotations

import functools
import inspect
import time
import uuid
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

# ── Context variable for per-call metric accumulation ─────────────────────────
# Set to a dict when inside a probe-wrapped call; None otherwise.
_probe_ctx: ContextVar[dict[str, Any] | None] = ContextVar("_probe_ctx", default=None)


# ── Public API: emit arbitrary metrics from inside a probe ────────────────────

def emit_metric(key: str, value: Any) -> None:
    """
    Attach an arbitrary key-value metric to the current probe run.

    Call from inside any probe-wrapped function (or any function it calls).
    Silently no-ops when called outside a probe context.

    Examples:
        emit_metric("input_len", len(expression))
        emit_metric("cache_hit", True)
        emit_metric("confidence", 0.92)
        emit_metric("parse_pass", "ast.literal_eval")
    """
    ctx = _probe_ctx.get()
    if ctx is not None:
        ctx[key] = value


# ── ProbeRun — the captured snapshot of a single call ────────────────────────

@dataclass
class ProbeRun:
    run_id: str
    probe_name: str
    description: str
    inputs: dict[str, str]        # param_name → safe-serialized value
    output: str | None            # safe-serialized return value
    wall_ms: float
    timestamp: str                # ISO-8601 UTC
    metrics: dict[str, Any]       # emit_metric() calls collected here
    status: str                   # "ok" | "error"
    error: str | None
    tags: list[str]


# ── In-process ring buffer ────────────────────────────────────────────────────

_MAX_RUNS = 500
_runs: list[ProbeRun] = []


def get_runs(limit: int = 100) -> list[ProbeRun]:
    """Return the most recent runs, newest first."""
    return list(reversed(_runs))[:limit]


def clear_runs() -> None:
    _runs.clear()


def _append(run: ProbeRun) -> None:
    _runs.append(run)
    if len(_runs) > _MAX_RUNS:
        del _runs[0]


# ── Serialization helpers ─────────────────────────────────────────────────────

def _safe_str(val: Any, max_len: int = 400) -> str:
    """Convert any value to a display-safe string, truncating if necessary."""
    if val is None:
        return "None"
    s = repr(val) if not isinstance(val, str) else val
    return s[:max_len] + ("…" if len(s) > max_len else "")


def _serialize_args(fn: Callable, args: tuple, kwargs: dict) -> dict[str, str]:
    """
    Map positional and keyword arguments to {param_name: repr(value)}.

    Falls back to positional keys ("arg_0", "arg_1", …) when the function
    signature cannot be introspected (built-ins, C extensions, etc.).
    """
    out: dict[str, str] = {}
    try:
        sig = inspect.signature(fn)
        params = list(sig.parameters.keys())
        # Skip 'self' / 'cls' for bound methods — they're noise in the UI
        if params and params[0] in ("self", "cls"):
            params = params[1:]
        for i, val in enumerate(args):
            name = params[i] if i < len(params) else f"arg_{i}"
            out[name] = _safe_str(val)
    except (ValueError, TypeError):
        for i, val in enumerate(args):
            out[f"arg_{i}"] = _safe_str(val)
    for k, v in kwargs.items():
        out[k] = _safe_str(v)
    return out


# ── The decorator ─────────────────────────────────────────────────────────────

def probe(
    description: str = "",
    name: str | None = None,
    tags: list[str] | None = None,
) -> Callable[[Callable], Callable]:
    """
    Instrument any callable for the benchmark WebUI.

    Parameters
    ──────────
    description : Human-readable explanation of what the function does and
                  what this probe is testing.  Shown in the WebUI detail view.
    name        : Override the probe's display name.  Defaults to
                  fn.__qualname__.
    tags        : Free-form labels (e.g. ["calculator", "arithmetic"]).
                  Used for filtering in the WebUI.

    The decorator captures:
      • All input arguments (name → safe repr)
      • The return value (safe repr)
      • Wall-clock execution time
      • Any emit_metric() calls made during execution
      • Exceptions (status = "error", error = "ExcType: message")

    Apply at *call-site* to avoid touching production code:

        probed = probe("Tests sqrt(144) == 12")(CalculatorAction().execute)
        result = probed(expression="sqrt(144)")
    """
    def decorator(fn: Callable) -> Callable:
        probe_name = name or fn.__qualname__
        probe_tags = list(tags or [])

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            metrics: dict[str, Any] = {}
            token  = _probe_ctx.set(metrics)
            t0     = time.perf_counter()
            result = None
            status = "ok"
            error  = None

            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as exc:
                status = "error"
                error  = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                wall_ms = (time.perf_counter() - t0) * 1000
                _probe_ctx.reset(token)
                _append(ProbeRun(
                    run_id=uuid.uuid4().hex[:8],
                    probe_name=probe_name,
                    description=description,
                    inputs=_serialize_args(fn, args, kwargs),
                    output=_safe_str(result) if status == "ok" else None,
                    wall_ms=wall_ms,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    metrics=dict(metrics),
                    status=status,
                    error=error,
                    tags=probe_tags,
                ))

        return wrapper
    return decorator
