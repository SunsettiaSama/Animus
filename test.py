"""
本地 DAG 端到端冒烟：infra LLMHandle + agent.flow DagOrchestrator（真实 LLM）。

默认启用 **SandboxManager**（文件/HTTP/Python 受限），与 WebUI 中带沙箱的 TaoLoop 行为一致。
SubAgentRunner.run_sync 当前未传 sandbox，因此在测试内对 TaoLoop.__init__ 做一次性注入。

用法：
  python test.py <llm.yaml> [选项]

  --mode full         全量 DAG 执行（默认）
  --mode single       最小单元：Planner 产出计划 → 仅执行第一个节点
  --goal "..."        目标文本
  --no-sandbox        不创建沙箱
  --sandbox-root DIR  沙箱工作区根目录
  --flow-log LEVEL    verbose / normal（默认）/ silent

示例：
  python test.py config\\llm_core\\config.yaml --mode single --goal "把 2025-05-01 是星期几写入 out.txt"
  python test.py config\\llm_core\\config.yaml --flow-log verbose
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pprint
import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


# ── sandbox / TaoLoop 注入 ───────────────────────────────────────────────────

def _install_sandbox_tao_loop(sandbox_mgr: object) -> Callable[[], None]:
    """将 SandboxManager 注入 TaoLoop（仅当构造参数 sandbox 为 None 时）。"""
    from agent.react.tao import TaoLoop

    _orig_init = TaoLoop.__init__

    def _wrapped(
        self,
        llm,
        executor,
        tool_descriptions,
        cfg,
        tool_category_summary: str = "",
        sandbox=None,
        risk_gate=None,
        scheduler_engine=None,
        reply_target=None,
        notify_fn=None,
        comm_rate_cfg=None,
    ):
        if sandbox is None:
            sandbox = sandbox_mgr
        _orig_init(
            self,
            llm,
            executor,
            tool_descriptions,
            cfg,
            tool_category_summary,
            sandbox,
            risk_gate,
            scheduler_engine,
            reply_target,
            notify_fn,
            comm_rate_cfg,
        )

    TaoLoop.__init__ = _wrapped

    def _restore() -> None:
        TaoLoop.__init__ = _orig_init

    return _restore


# ── flow 日志格式化 ──────────────────────────────────────────────────────────

def _format_flow_event_normal(ev) -> str:
    k = ev.kind
    pl = ev.payload
    if k == "plan.start":
        t = (pl.get("title") or "")[:72]
        nc = pl.get("node_count", "?")
        return f"[flow] plan.start  title={t!r}  nodes={nc}"
    if k == "plan.complete":
        return f"[flow] plan.complete  status={pl.get('status', pl)!r}"
    if k == "task.start":
        return f"[flow] task.start  {pl.get('task_id', '?')}"
    if k == "task.complete":
        tid = pl.get("task_id", "?")
        sub = pl.get("kind", "")
        rp = pl.get("result_preview", "")
        bits = [tid]
        if sub:
            bits.append(f"kind={sub}")
        if rp:
            bits.append(f"preview={str(rp)[:60]!r}")
        return "[flow] task.complete  " + "  ".join(bits)
    if k == "task.failed":
        return f"[flow] task.FAIL  {pl.get('task_id', '?')}  err={str(pl.get('error', ''))[:120]!r}"
    if k == "task.skipped":
        return f"[flow] task.skip  {pl.get('task_id', '?')}  {pl.get('reason', '')!r}"
    if k == "task.flat_expand":
        return f"[flow] flat_expand  parent={pl.get('task_id', '?')}  sub={pl.get('sub_count', '?')}"
    if k == "task.nested_run":
        return f"[flow] nested_run  parent={pl.get('task_id', '?')}  sub={pl.get('sub_count', '?')}"
    if k in ("replan.start", "replan.complete"):
        return f"[flow] {k}  {pl!r}"
    return f"[flow] {k}  {pl!r}"


def _format_flow_event_verbose(idx: int, ev) -> str:
    body = {
        "index": idx,
        "plan_id": ev.plan_id,
        "kind": ev.kind,
        "payload": dict(ev.payload),
    }
    return f"[flow] --- 事件 #{idx} ---\n{json.dumps(body, ensure_ascii=False, indent=2)}"


def _print_flow_replay(events: list, out) -> None:
    line = "=" * 72
    print(line, file=out)
    print(f"Flow 事件完整回放（共 {len(events)} 条）", file=out)
    print(line, file=out)
    pp = pprint.PrettyPrinter(indent=2, width=100, stream=out)
    for i, ev in enumerate(events, start=1):
        print(f"\n--- #{i} ---", file=out)
        pp.pprint(asdict(ev))
    print(line, file=out)


# ── 参数解析 & 初始化 ────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="DagOrchestrator + LLMHandle + 可选沙箱")
    ap.add_argument(
        "cfg",
        nargs="?",
        default=os.environ.get("LLM_CFG", "").strip(),
        help="LLM YAML 路径；可省略则用环境变量 LLM_CFG",
    )
    ap.add_argument(
        "--mode",
        choices=("full", "single"),
        default="full",
        help="full=全量 DAG（默认），single=最小单元 planner→单节点执行",
    )
    ap.add_argument(
        "--goal",
        default="列出 3 条「学习 Python asyncio」的短小步骤（每步一行，不写废话）。",
        help="任务目标文本",
    )
    ap.add_argument("--no-sandbox", action="store_true")
    ap.add_argument("--sandbox-root", type=str, default="")
    ap.add_argument("--sandbox-config", type=str, default="")
    ap.add_argument(
        "--flow-log",
        choices=("verbose", "normal", "silent"),
        default="normal",
        metavar="LEVEL",
    )
    return ap.parse_args()


def _setup_sandbox(ns: argparse.Namespace):
    """返回 (sandbox_mgr | None, restore_fn | None)。"""
    if ns.no_sandbox:
        return None, None

    from config.infra.sandbox_config import SandboxConfig
    from infra.sandbox import SandboxManager

    sc_path = (ns.sandbox_config or "").strip()
    if sc_path:
        sp = Path(sc_path).resolve()
        if not sp.is_file():
            sys.stderr.write(f"找不到沙箱配置: {sp}\n")
            raise SystemExit(2)
        sb_cfg = SandboxConfig.from_yaml(str(sp))
    else:
        sb_cfg = SandboxConfig()

    root_arg = (ns.sandbox_root or "").strip()
    ws = Path(root_arg).resolve() if root_arg else (ROOT / ".react" / "test_flow_sandbox")
    sb_cfg.workspace_root = str(ws)

    sandbox_mgr = SandboxManager(sb_cfg)
    sandbox_mgr.start()
    print(f"[sandbox] workspace_root={sandbox_mgr.status()['workspace_root']}")

    restore_tao = _install_sandbox_tao_loop(sandbox_mgr)
    return sandbox_mgr, restore_tao


# ── mode=full：全量 DAG ──────────────────────────────────────────────────────

async def _run_full(ns: argparse.Namespace, llm_yaml: str, llm_call: Callable) -> None:
    from agent.flow.base.budget import DecompositionBudget
    from agent.flow.base.dag_orchestrator import DagOrchestrator
    from agent.flow.base.defaults import register_defaults
    from agent.flow.base.orchestration import OrchestratorEvent
    from agent.flow.base.registry import get_registry

    register_defaults(llm_yaml, llm_call_fn=llm_call)
    reg = get_registry()
    atomic = reg.build_atomic_planner(llm_yaml)
    if atomic is None:
        raise RuntimeError("register_defaults 后仍无 AtomicPlanner")

    budget = DecompositionBudget(max_review_rounds=0)
    orch = DagOrchestrator(
        planner=None,
        atomic_planner=atomic,
        registry=reg,
        replanner=None,
        budget=budget,
    )

    flow_journal: list[OrchestratorEvent] = []
    flow_level = ns.flow_log

    def on_event(ev: OrchestratorEvent) -> None:
        if flow_level == "silent":
            return
        if flow_level == "verbose":
            flow_journal.append(ev)
            print(_format_flow_event_verbose(len(flow_journal), ev))
            return
        print(_format_flow_event_normal(ev))

    orch.subscribe(on_event)

    out = await orch.run(ns.goal)
    print("---")
    print(f"status={out.status!r}  plan_id={out.plan_id!r}")
    if out.answer:
        print(f"answer={out.answer!r}")
    if out.spec is not None:
        print(f"nodes={list(out.spec.all_node_ids())}")
    if flow_level == "verbose" and flow_journal:
        _print_flow_replay(flow_journal, sys.stdout)


# ── mode=single：最小单元（AtomicPlanner → 单节点执行） ─────────────────────

async def _run_single(ns: argparse.Namespace, llm_yaml: str, llm_call: Callable) -> None:
    """
    最小单元路径：
      NodeManifest（手动构造）
        → AtomicPlanner.assess()  →  TopologyDecision（atomic / flat / nested）
        → SubAgentManifestExecutor.run(manifest, {})  →  answer

    AtomicPlanner 是 DagOrchestrator 在每个节点上真正调用的规划层，
    负责决定该节点是否需要拆解（flat / nested）还是直接执行（atomic）。
    Cluster 层的 PlannerAgent 用于生成多任务计划，不属于单节点的最小路径。

    NodeManifest 可写字段（AtomicPlanner / executor 直接读取）：
      task_id          唯一标识（snake_case）
      description      自然语言任务说明
      depends_on       上游节点 id 元组（此处单节点故为空）
      input_contract   对输入数据的期望（供 LLM 理解上下文）
      output_contract  对产出物的约束（供 LLM 知晓目标格式）
      tool_package     工具包名（"executor"/"researcher"/"code"/"full" 等）
      max_steps        TAO 最大步数上限
      system_note      追加到 executor 系统提示的任务级约束
      topology         初始拓扑提示（通常保持 atomic）
    """
    import asyncio as _asyncio
    from agent.flow.base.budget import DecompositionBudget, TopologyKind
    from agent.flow.base.components.atomic_planner import AtomicPlanner
    from agent.flow.base.components.atomic_reviewer import AtomicReviewer
    from agent.flow.base.components.node_spec import NodeManifest, ObservationMode
    from agent.flow.base.defaults import SubAgentManifestExecutor

    loop = _asyncio.get_running_loop()

    # ── 1. 手动构造 NodeManifest（零 Cluster 层依赖）────────────────────────
    manifest = NodeManifest(
        task_id="single_task",
        description=ns.goal,
        input_contract="无上游依赖",
        output_contract="直接回答目标问题",
        tool_package="executor",   # 可改为 "full" / "researcher" / "code" 等
        max_steps=8,
        observation_mode=ObservationMode.distilled,
    )

    print(f"\n[single] manifest:")
    print(f"  task_id        = {manifest.task_id!r}")
    print(f"  description    = {manifest.description[:80]!r}")
    print(f"  tool_package   = {manifest.tool_package!r}")
    print(f"  max_steps      = {manifest.max_steps}")
    print(f"  input_contract = {manifest.input_contract!r}")
    print(f"  output_contract= {manifest.output_contract!r}")

    # ── 2. AtomicPlanner.assess()：决定拓扑 ─────────────────────────────────
    reviewer = AtomicReviewer(llm_call)
    atomic_planner = AtomicPlanner(llm_call, reviewer=reviewer)
    budget = DecompositionBudget(max_depth=1, max_review_rounds=0)

    print("\n[single] AtomicPlanner.assess() ...")
    decision = await atomic_planner.assess(manifest, budget)
    print(f"[single] topology = {decision.kind.value!r}  reason = {decision.reason!r}")
    if decision.sub_manifests:
        print(f"[single] sub_manifests ({len(decision.sub_manifests)}):")
        for sm in decision.sub_manifests:
            print(f"  {sm.task_id}  depends_on={sm.depends_on}  pkg={sm.tool_package!r}")

    # ── 3. 执行（始终对 manifest 本身执行；若 flat/nested 只做展示）──────────
    # 在真实 DagOrchestrator 中，flat 会展开为同层兄弟节点，nested 会起子图。
    # 这里单节点测试直接执行原始 manifest，以最小依赖验证执行路径。
    if decision.kind != TopologyKind.atomic:
        print(f"\n[single] 决策为 {decision.kind.value}，演示时仍直接执行原始节点。")

    print("\n[single] SubAgentManifestExecutor.run() ...")
    executor = SubAgentManifestExecutor(llm_yaml)
    answer = await loop.run_in_executor(None, executor.run, manifest, {})
    print(f"\n[single] answer:\n{answer}")


# ── 入口 ─────────────────────────────────────────────────────────────────────

def _run() -> None:
    from config.llm_core.config import LLMConfig
    from infra.llm import LLM, LLMHandle
    from langchain_core.messages import HumanMessage, SystemMessage

    ns = _parse_args()
    cfg_path = (ns.cfg or "").strip()
    if not cfg_path:
        sys.stderr.write(
            "用法: python test.py <llm.yaml> [--mode single|full] [--goal \"...\"]\n"
            "  或  LLM_CFG=/path/to/llm.yaml python test.py\n"
        )
        raise SystemExit(2)

    p = Path(cfg_path).resolve()
    if not p.is_file():
        sys.stderr.write(f"找不到 LLM 配置文件: {p}\n")
        raise SystemExit(2)

    llm_yaml = str(p)
    lc = LLMConfig.from_yaml(llm_yaml)
    if not lc.model:
        sys.stderr.write("YAML 中需配置 model\n")
        raise SystemExit(2)

    sandbox_mgr, restore_tao = _setup_sandbox(ns)

    core = LLM(lc)
    handle = LLMHandle(core)

    def llm_call(system_prompt: str, user_prompt: str) -> str:
        return handle.generate_messages(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
        )

    try:
        if ns.mode == "single":
            asyncio.run(_run_single(ns, llm_yaml, llm_call))
        else:
            asyncio.run(_run_full(ns, llm_yaml, llm_call))
    finally:
        if restore_tao is not None:
            restore_tao()
        if sandbox_mgr is not None:
            sandbox_mgr.stop()


if __name__ == "__main__":
    _run()
