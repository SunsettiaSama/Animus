#!/usr/bin/env python3
"""Worker 冒烟：sandbox + RiskGate + agent state + TaoLoop 跑一轮真实任务。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    from config.agent.risk_config import RiskConfig
    from infra.sandbox import SandboxManager
    from worker.profile import SubAgentConfig
    from worker.tools.manager import ToolManager
    from worker.tools.risk.gate import RiskGate
    from worker.runner import SubAgentRunner
    from worker.state import build_agent_state_service

    llm_cfg = ROOT / "config" / "llm_core" / "config.yaml"
    if not llm_cfg.is_file():
        raise FileNotFoundError(llm_cfg)

    work_dir = ROOT / ".react" / "workspace" / "worker_smoke"
    work_dir.mkdir(parents=True, exist_ok=True)

    sandbox = SandboxManager()
    sandbox._cfg.workspace_root = str(work_dir)
    sandbox.start()

    # Smoke 允许 HIGH（含潜伏 shell），避免人工审批卡住。
    risk = RiskGate.from_config(RiskConfig(enabled=True, auto_approve_level="high"))

    state_dir = ROOT / ".react" / "worker_smoke_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    agent_state = build_agent_state_service(state_dir=state_dir, llm=None, soul=None)

    tm = ToolManager()
    prompt = tm.primary_descriptions(tm.prompt_tool_names())
    print("=== prompt tools ===")
    for name in prompt:
        print(f"  - {name}")
    print("=== category_summary ===")
    print(tm.category_summary())

    profile = SubAgentConfig(llm_cfg_path=str(llm_cfg)).profiles["executor"]
    runner = SubAgentRunner()

    instruction = (
        "请完成以下小任务并给出最终答案：\n"
        "1) 用 get_datetime 查询当前时间；\n"
        "2) 用 calculator 计算 23*47；\n"
        "3) 用 command_lookup 查询 powershell 如何显示当前目录（不要臆造命令）；\n"
        "4) 若 lookup 返回了 powershell_run 模板，再用 powershell_run 执行 Get-Location；\n"
        "最后 finish，简要汇总三步结果。"
    )

    events: list[str] = []

    def on_event(event) -> None:
        name = type(event).__name__
        if name == "StepEvent":
            action = getattr(event, "action", "")
            thought = (getattr(event, "thought", "") or "")[:120]
            obs = (getattr(event, "observation", "") or "")[:200]
            line = f"[step {getattr(event, 'index', '?')}] action={action}\n  T: {thought}\n  O: {obs}"
            events.append(line)
            print(line, flush=True)
        elif name == "FinishEvent":
            print(f"[finish] {(getattr(event, 'answer', '') or '')[:500]}", flush=True)
        elif name == "ApprovalRequestEvent":
            print(f"[approval] {getattr(event, 'tool_name', '')}", flush=True)

    print("\n=== running worker ===", flush=True)
    result = runner.run_sync(
        instruction,
        profile,
        str(llm_cfg),
        event_callback=on_event,
        sandbox=sandbox,
        risk_gate=risk,
        agent_state_service=agent_state,
    )

    print("\n=== result ===")
    print(f"step_count={result.get('step_count')}")
    print(f"answer={result.get('answer', '')[:800]}")
    units = result.get("units") or []
    print(f"units={len(units)}")
    for u in units:
        kind = u.get("kind")
        payload = u.get("payload") or {}
        if kind == "user":
            print(f"  [{kind}] {str(payload.get('text', ''))[:100]}")
        elif kind == "thought_action":
            print(f"  [{kind}] action={payload.get('action')}")
        else:
            print(
                f"  [{kind}] tool={payload.get('tool')} "
                f"obs={str(payload.get('observation', ''))[:120]}"
            )

    actions = [s.get("action") for s in (result.get("steps") or [])]
    print(f"actions={actions}")
    ok = bool(result.get("answer")) and result.get("step_count", 0) >= 1
    if "command_lookup" not in actions and "get_datetime" not in actions and "calculator" not in actions:
        print("WARN: expected at least one of get_datetime/calculator/command_lookup")
    print("OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
