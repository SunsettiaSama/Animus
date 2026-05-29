"""
本地端到端冒烟脚本（真实 LLM / 可选 infra）。

模式
----
  full / single     DagOrchestrator + 可选 Sandbox（默认 full）
  persona-drift     Persona 月度 self_concept 漂移演示（10 条记忆 + 画像 → 演化前后对比）
  soul-evolution    Soul 全链路：speak → life → memory → compose 检索（真实 LLM + MySQL + embedding）

用法：
  python test.py <llm.yaml> [选项]

  --mode full|single|persona-drift|soul-evolution
  --goal "..."        目标文本（DAG 模式）
  --no-sandbox        不创建沙箱（DAG 模式）
  --no-infra          persona-drift：跳过 BGE/Qdrant，聚类退化为 focus 分桶
  --persona-dir DIR   persona-drift 工作目录（默认 .react/test_persona_drift）
  --flow-log LEVEL    verbose / normal / silent（DAG 模式）

示例（推荐 conda 环境 LLMs）：
  conda run -n LLMs python test.py config\\llm_core\\config.yaml --mode soul-evolution
  conda run -n LLMs python test.py config\\llm_core\\config.yaml --mode persona-drift
  conda run -n LLMs python test.py config\\llm_core\\config.yaml --mode single --goal "把 2025-05-01 是星期几写入 out.txt"

  soul-evolution 需 MySQL（可先：docker compose -f docker/docker-compose-db.yml up -d mysql）
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
        **kwargs,
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
            **kwargs,
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
        choices=("full", "single", "persona-drift", "soul-evolution"),
        default="full",
        help="full|single=DAG；persona-drift=Persona 漂移；soul-evolution=Soul 全链路",
    )
    ap.add_argument(
        "--goal",
        default="列出 3 条「学习 Python asyncio」的短小步骤（每步一行，不写废话）。",
        help="任务目标文本",
    )
    ap.add_argument("--no-sandbox", action="store_true")
    ap.add_argument(
        "--no-infra",
        action="store_true",
        help="persona-drift / soul-evolution：跳过 BGE+Qdrant",
    )
    ap.add_argument(
        "--soul-dir",
        type=str,
        default="",
        help="soul-evolution 工作目录（默认 .react/test_soul_evolution）",
    )
    ap.add_argument(
        "--session-id",
        type=str,
        default="soul-evolution",
        help="soul-evolution 会话 id",
    )
    ap.add_argument(
        "--memory-wait",
        type=float,
        default=4.0,
        help="soul-evolution：闭合会话后等待 memory 异步写入秒数",
    )
    ap.add_argument(
        "--persona-dir",
        type=str,
        default="",
        help="persona-drift 数据目录（默认 .react/test_persona_drift）",
    )
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


# ── mode=persona-drift：真实 Persona 月度演化 ─────────────────────────────────

def _log_section(title: str) -> None:
    line = "=" * 72
    print(f"\n{line}\n{title}\n{line}")


def _log_sub(title: str) -> None:
    print(f"\n--- {title} ---")


def _print_profile(profile) -> None:
    print(profile.render())


def _print_self_concept(concept, *, label: str = "") -> None:
    if label:
        print(f"[{label}]")
    print(f"叙事 ({concept.updated_at}):")
    print(concept.narrative.strip() or "（空）")
    print("信念:")
    if not concept.beliefs:
        print("  （无）")
        return
    for b in concept.beliefs:
        print(f"  · [{b.strength.value}] {b.content}")


def _print_delta(delta) -> None:
    print(f"  narrative : {delta.narrative[:200]!r}" if delta.narrative else "  narrative : （不变）")
    print(f"  adds      : {delta.adds}")
    print(f"  upgrades  : {delta.upgrades}")
    print(f"  removes   : {delta.removes}")


class _LoggingLLM:
    """包装 BaseLLM，打印每次蒸馏调用的摘要。"""

    def __init__(self, inner) -> None:
        self._inner = inner
        self._n = 0

    def generate_messages(self, messages, **kwargs) -> str:
        self._n += 1
        sys_msg = str(getattr(messages[0], "content", ""))[:60] if messages else ""
        user_msg = str(getattr(messages[-1], "content", "")) if messages else ""
        preview = user_msg.replace("\n", " ")[:120]
        print(f"\n  [LLM #{self._n}] system={sys_msg!r} … user≈{preview!r}")
        raw = self._inner.generate_messages(messages, **kwargs)
        shown = raw.strip().replace("\n", " ")[:280]
        print(f"  [LLM #{self._n}] response≈{shown!r}")
        return raw


class _InMemoryDriftPort:
    """模拟 Memory.list_drift_units，供漂移回查 raw units。"""

    def __init__(self, units: list) -> None:
        self._units = {u.id: u for u in units}

    def list_drift_units(self, *, month: str, anchor_unit_ids=None, limit: int = 120):
        anchors = [uid for uid in (anchor_unit_ids or []) if uid]
        seen: set[str] = set()
        out: list = []
        for uid in anchors:
            unit = self._units.get(uid)
            if unit is None or unit.id in seen:
                continue
            seen.add(unit.id)
            out.append(unit)
        if len(out) < limit:
            for unit in self._units.values():
                if unit.id in seen:
                    continue
                if unit.created_at.strftime("%Y-%m") != month:
                    continue
                seen.add(unit.id)
                out.append(unit)
                if len(out) >= limit:
                    break
        return out[:limit]


def _seed_persona_workspace(persona_dir: Path) -> tuple[list, list[dict]]:
    """写入 profile / self_concept，并构造 10 条本月 memory units + buffer 元数据。"""
    from datetime import datetime, timezone

    from agent.soul.memory.unit import FactualMemory, Valence
    from agent.soul.persona.profile.profile import PersonaProfile
    from agent.soul.persona.self_concept.concept import Belief, BeliefStrength, SelfConcept
    from agent.soul.persona.self_concept.store import SelfConceptStore
    from agent.soul.persona.profile.store import ProfileStore

    persona_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    month = now.strftime("%Y-%m")

    profile = PersonaProfile(
        name="林知遥",
        background_facts=[
            "在一家产品团队做后端开发，常参与跨组评审",
            "习惯把复杂问题拆成可验证的小步骤",
        ],
        core_traits=["谨慎", "负责", "内省", "慢热"],
        interpersonal_style="先听再表态，倾向书面确认关键结论",
        emotional_expressiveness="表面克制，私下会反复回想对话细节",
        values=["可靠交付", "诚实沟通", "尊重边界"],
        ethical_stances=["不替他人做未经确认的承诺"],
        cognitive_style="结构化、偏保守验证",
        reasoning_pattern="先找反例，再收敛到可执行方案",
        core_motivation="成为团队里‘让人放心’的技术搭档",
        avoidance_pattern="回避当众被追问细节却答不上来",
        stress_response="短期加工作量，长期会沉默并自我怀疑",
        boundaries=["非工作时间不承接临时大改需求"],
        built=True,
        built_at="demo-seed-v1",
    )
    ProfileStore(str(persona_dir)).save_profile(profile)

    concept = SelfConcept(
        narrative=(
            "我把自己看作一个需要时间热身、但一旦进入状态就能稳定交付的人。"
            "我重视承诺，也因此在协作前常会多确认一步。"
        ),
        beliefs=[
            Belief(
                content="我擅长把复杂问题拆成可验证的小步骤",
                strength=BeliefStrength.established,
                source="build",
            ),
            Belief(
                content="我在跨组沟通前容易犹豫",
                strength=BeliefStrength.emerging,
                source="build",
            ),
        ],
    )
    SelfConceptStore(str(persona_dir)).save(concept)

    event_specs = [
        ("evt-01", "跨组评审", "产品临时改需求，我在评审里当场指出风险，会议气氛变僵", "焦虑", Valence.negative, 0.72),
        ("evt-02", "跨组评审", "会后同事私信说我的提醒有价值，但希望语气更柔和", "释然", Valence.mixed, 0.58),
        ("evt-03", "跨组评审", "我改用书面列出风险清单再开会，对方接受度明显提高", "踏实", Valence.positive, 0.65),
        ("evt-04", "跨组评审", "又一次评审前我反复改 PPT，担心被追问细节", "紧张", Valence.negative, 0.55),
        ("evt-05", "项目延期", "核心接口延期两天，我主动加班补齐联调窗口", "压力", Valence.negative, 0.68),
        ("evt-06", "项目延期", "leader 说‘先保上线’，我内心觉得测试覆盖不足", "矛盾", Valence.mixed, 0.61),
        ("evt-07", "项目延期", "上线后小故障被快速修复，我松了口气但也更警惕", "警觉", Valence.neutral, 0.52),
        ("evt-08", "边界拒绝", "非工作时间收到大改需求，我明确拒绝并提议周一处理", "坚定", Valence.positive, 0.70),
        ("evt-09", "边界拒绝", "对方表示理解，我第一次没有为拒绝而内疚", "轻松", Valence.positive, 0.63),
        ("evt-10", "边界拒绝", "我复盘后发现‘提前写清边界’比事后解释更省力", "领悟", Valence.positive, 0.66),
    ]

    units: list[FactualMemory] = []
    for uid, focus, fact, emotion, valence, intensity in event_specs:
        unit = FactualMemory(
            id=uid,
            focus=focus,
            fact=fact,
            perception=f"我注意到：{fact}",
            emotion=emotion,
            emotion_intensity=intensity,
            valence=valence,
            base_activation=max(0.35, intensity),
            life_event_id=uid,
        )
        unit.created_at = now
        units.append(unit)

    cluster_payloads = [
        {
            "theme": "跨组评审中的表达与确认",
            "tick_id": "wander-tick-1",
            "unit_ids": ["evt-01", "evt-02", "evt-03", "evt-04"],
            "mass": 2.4,
            "persona_score": 0.78,
        },
        {
            "theme": "项目延期与交付压力",
            "tick_id": "wander-tick-2",
            "unit_ids": ["evt-05", "evt-06", "evt-07"],
            "mass": 1.9,
            "persona_score": 0.71,
        },
        {
            "theme": "非工作时间的边界",
            "tick_id": "wander-tick-3",
            "unit_ids": ["evt-08", "evt-09", "evt-10"],
            "mass": 2.0,
            "persona_score": 0.74,
        },
    ]
    return units, cluster_payloads


def _run_persona_drift(ns: argparse.Namespace, llm_yaml: str) -> None:
    from dataclasses import replace

    from config.agent.persona_config import PersonaConfig
    from config.llm_core.config import LLMConfig
    from config.soul.memory.infra_config import SoulMemoryInfraConfig
    from infra.llm import LLM
    from infra.memory import MemoryInfraService

    from agent.soul.persona.buffer import (
        cluster_memory_units,
        current_month,
        DriftDistillWriter,
    )
    from agent.soul.persona.manager import PersonaManager
    from agent.soul.persona.self_concept.concept import SelfConcept

    persona_dir = Path(ns.persona_dir).resolve() if ns.persona_dir.strip() else (ROOT / ".react" / "test_persona_drift")
    target_month = current_month()

    _log_section("Persona 月度漂移演示 — 初始化")
    print(f"persona_dir = {persona_dir}")
    print(f"target_month = {target_month}")
    print(f"llm_yaml    = {llm_yaml}")

    units, cluster_payloads = _seed_persona_workspace(persona_dir)
    print(f"已种子化：profile + self_concept + {len(units)} 条 memory units + {len(cluster_payloads)} 条 buffer 信号")

    lc = LLMConfig.from_yaml(llm_yaml)
    core = LLM(lc)
    llm = _LoggingLLM(core)

    infra_cfg = SoulMemoryInfraConfig.load_default()
    if ns.no_infra:
        infra_cfg = replace(infra_cfg, enabled=False)
        print("\n[infra] 已禁用（--no-infra），聚类将使用 focus 分桶")
        embedder = None
    else:
        print("\n[infra] 启用 MemoryInfraService（BGE + Qdrant）…")
        infra = MemoryInfraService.build(infra_cfg)
        infra.warm_up()
        embedder = infra.retriever_embedder()
        print(f"[infra] embedder={'OK' if embedder is not None else 'NONE'}")

    persona_cfg = PersonaConfig(
        enabled=True,
        persona_dir=str(persona_dir),
        evolution_enabled=False,
    )
    manager = PersonaManager(persona_cfg, llm=llm)
    memory_port = _InMemoryDriftPort(units)
    manager.set_memory_port(memory_port)
    manager.set_embedder(embedder)

    _log_section("演化前 — 静态画像（Profile）")
    _print_profile(manager.profile)

    concept_before = SelfConcept.from_dict(manager.self_concept.to_dict())
    _log_section("演化前 — 慢变自我（SelfConcept）")
    _print_self_concept(concept_before, label="BEFORE")

    _log_section("Step 1 · Buffer 采集（模拟 heartbeat wander → persona_clusters）")
    buf_result = manager.record_cluster_signals(cluster_payloads)
    print(f"record_cluster_signals → applied={buf_result['applied']} pending={buf_result['buffer']['pending']}")
    for sig in manager.buffer.pending():
        print(f"  · theme={sig.theme!r} units={sig.unit_ids}")

    _log_section("Step 2 · Memory 回查 raw units")
    anchor_ids: list[str] = []
    for sig in manager.buffer.pending_for_month(target_month):
        anchor_ids.extend(sig.unit_ids)
    anchor_ids = list(dict.fromkeys(anchor_ids))
    drift_units = memory_port.list_drift_units(
        month=target_month,
        anchor_unit_ids=anchor_ids,
        limit=120,
    )
    print(f"list_drift_units → {len(drift_units)} units（anchors={len(anchor_ids)}）")
    for u in drift_units:
        print(f"  [{u.id}] {u.focus} | {u.fact[:48]}… | 情绪={u.emotion}({u.emotion_intensity:.2f})")

    _log_section("Step 3 · Embedding 聚类")
    clusters = cluster_memory_units(drift_units, embedder)
    print(f"clusters = {len(clusters)}")
    for i, cl in enumerate(clusters, start=1):
        print(f"\n  簇 #{i} theme={cl.theme!r} size={len(cl.units)} cohesion={cl.cohesion:.3f}")
        for line in cl.lines(max_lines=4):
            print(f"    - {line}")

    _log_section("Step 4 · 分簇蒸馏（DriftDistillWriter.distill_cluster）")
    writer = DriftDistillWriter(llm)
    cluster_drafts = []
    for cl in clusters:
        draft = writer.distill_cluster(cl, manager.profile, manager.self_concept)
        cluster_drafts.append(draft)
        print(f"\n  簇「{draft.theme}」insight:")
        print(f"    {draft.insight or '（空）'}")
        if draft.adds:
            print(f"    adds={draft.adds}")
        if draft.upgrades:
            print(f"    upgrades={draft.upgrades}")

    _log_section("Step 5 · 向上合并（reduce_drafts）")
    month_draft = writer.reduce_drafts(cluster_drafts, month=target_month)
    print(f"month={month_draft.month}")
    print(f"month_insight:\n  {month_draft.insight or '（空）'}")

    _log_section("Step 6 · 对照画像修订（revise_against_portrait）")
    delta = writer.revise_against_portrait(manager.profile, manager.self_concept, month_draft)
    print("SelfConceptDelta:")
    _print_delta(delta)

    if delta.is_empty():
        print("\n[结果] delta 为空，跳过 apply。")
        return

    _log_section("Step 7 · 写回 self_concept（apply_delta + mark_consolidated）")
    apply_result = manager.apply_self_concept_delta(delta)
    pending_ids = [s.id for s in manager.buffer.pending_for_month(target_month)]
    marked = manager.buffer.mark_consolidated(pending_ids)
    from agent.soul.persona.buffer.store import ExperienceBufferStore

    manager._buffer_store.save(manager.buffer)
    manager._buffer_meta = manager._buffer_store.touch_drift_run(target_month)

    print(f"apply → {apply_result}")
    print(f"buffer mark_consolidated → {marked} signals")

    _log_section("演化后 — SelfConcept 对比")
    concept_after = manager.self_concept
    _print_self_concept(concept_after, label="AFTER")

    _log_sub("叙事 diff")
    if concept_before.narrative.strip() != concept_after.narrative.strip():
        print("  BEFORE:", concept_before.narrative.strip())
        print("  AFTER :", concept_after.narrative.strip())
    else:
        print("  （叙事未变）")

    _log_sub("信念 diff")
    before_map = {b.content: b.strength.value for b in concept_before.beliefs}
    after_map = {b.content: b.strength.value for b in concept_after.beliefs}
    added = [c for c in after_map if c not in before_map]
    removed = [c for c in before_map if c not in after_map]
    changed = [
        c for c in before_map
        if c in after_map and before_map[c] != after_map[c]
    ]
    if added:
        print("  新增:", added)
    if removed:
        print("  移除:", removed)
    if changed:
        for c in changed:
            print(f"  升级/降级: {before_map[c]} → {after_map[c]}  |  {c}")
    if not added and not removed and not changed:
        print("  （信念列表无结构变化）")

    _log_section("完成")
    print(f"portrait_revision = {manager.portrait_revision()}")
    print(f"buffer pending    = {manager.buffer.summary()['pending']}")
    print(f"数据目录          = {persona_dir}")


# ── mode=soul-evolution：life → memory → speak compose ───────────────────────

def _seed_soul_persona(persona_dir: Path) -> None:
    from agent.soul.persona.profile.profile import PersonaProfile
    from agent.soul.persona.profile.store import ProfileStore
    from agent.soul.persona.self_concept.concept import Belief, BeliefStrength, SelfConcept
    from agent.soul.persona.self_concept.store import SelfConceptStore

    persona_dir.mkdir(parents=True, exist_ok=True)
    ProfileStore(str(persona_dir)).save_profile(
        PersonaProfile(
            name="林知遥",
            background_facts=["产品团队后端开发，习惯把问题拆成小步骤验证"],
            core_traits=["谨慎", "内省", "负责"],
            values=["诚实沟通", "可靠交付"],
            built=True,
            built_at="soul-evolution-seed",
        )
    )
    SelfConceptStore(str(persona_dir)).save(
        SelfConcept(
            narrative="我在学习如何更稳定地陪伴用户，重视承诺也因此在协作前会多确认一步。",
            beliefs=[
                Belief(
                    content="我擅长把复杂问题拆成可验证的小步骤",
                    strength=BeliefStrength.established,
                    source="build",
                ),
            ],
        )
    )


def _snippet(text: str, *, limit: int = 480) -> str:
    one = text.replace("\n", " ").strip()
    return one if len(one) <= limit else one[: limit - 3] + "..."


def _run_soul_evolution(ns: argparse.Namespace, llm_yaml: str, llm) -> None:
    import time
    from dataclasses import replace

    from config.agent.persona_config import PersonaConfig
    from config.infra.db_config import DBConfig
    from config.soul.config import SoulConfig
    from config.soul.memory.infra_config import SoulMemoryInfraConfig
    from infra.memory import MemoryInfraService

    from agent.soul.persona.profile.store import ProfileStore
    from agent.soul.service import SoulService

    work_root = Path(ns.soul_dir).resolve() if ns.soul_dir.strip() else (ROOT / ".react" / "test_soul_evolution")
    persona_dir = work_root / "persona"
    life_dir = work_root / "life"
    session_id = (ns.session_id or "soul-evolution").strip()

    _log_section("Soul 全链路演化 — 初始化")
    print(f"work_root   = {work_root}")
    print(f"session_id  = {session_id}")
    print(f"llm_yaml    = {llm_yaml}")
    print("python env  = 建议使用 conda 环境 LLMs")

    _seed_soul_persona(persona_dir)
    print(f"已种子化 persona → {persona_dir}")

    db_cfg = DBConfig.load_default()
    if not db_cfg.mysql.enabled:
        sys.stderr.write("MySQL 未启用：请在 config/infra/db.yaml 中设置 mysql.enabled=true\n")
        raise SystemExit(2)
    mysql = db_cfg.mysql.build_client()
    print(f"[mysql] 连接 {db_cfg.mysql.url} …")
    print("        若拒绝连接，请先启动：docker compose -f docker/docker-compose-db.yml up -d mysql")
    mysql.ping()
    print("[mysql] ping OK")

    infra_cfg = SoulMemoryInfraConfig.load_default()
    memory_infra = None
    if ns.no_infra:
        infra_cfg = replace(infra_cfg, enabled=False)
        memory_infra = MemoryInfraService(
            cfg=infra_cfg,
            embedding=None,
            vectors=None,
        )
        print("[infra] 已禁用（--no-infra）")
    else:
        print("[infra] 加载 BGE + Qdrant …")
        memory_infra = MemoryInfraService.build(infra_cfg)
        memory_infra.warm_up()
        print(f"[infra] embedder={'OK' if memory_infra.retriever_embedder() else 'NONE'}")

    persona_cfg = PersonaConfig(
        enabled=True,
        persona_dir=str(persona_dir),
        evolution_enabled=False,
    )
    soul = SoulService(
        life_dir=str(life_dir),
        persona_cfg=persona_cfg,
        mysql_client=mysql,
        primary_llm=llm,
        cfg=SoulConfig.load_default(),
        memory_infra=memory_infra,
    )
    soul.start()
    print(f"[soul] state={soul.state}")

    prompts = [
        "你好，我是联调用户小遥。",
        "上周跨组评审出了意外变故，我久久不能平静，想和你聊聊。",
        "你还记得我刚才说的评审那件事吗？",
    ]

    _log_section("Step 1 · 打开 dialogue 会话")
    soul.start_dialogue_session(session_id)
    print(f"profile.name = {ProfileStore(str(persona_dir)).load_profile().name!r}")

    _log_section("Step 2 · Speak 轮次（life 记账 + 上下文蒸馏）")
    for i, prompt in enumerate(prompts, start=1):
        print(f"\n--- turn #{i} user ---\n{prompt}")
        payload = soul.speak_turn(prompt, session_id=session_id, stream=False)
        answer = str(payload.get("answer") or "").strip()
        bundle_log = payload.get("bundle") if isinstance(payload.get("bundle"), dict) else {}
        print(f"agent≈{_snippet(answer)}")
        if bundle_log:
            print(f"bundle: {bundle_log}")
        time.sleep(0.5)

    _log_section("Step 3 · 闭合会话 → life chronicle + memory buffer 整合")
    close_out = soul.close_dialogue_interaction(session_id)
    print(f"close_dialogue → {close_out}")
    wait_sec = max(0.0, float(ns.memory_wait))
    if wait_sec > 0:
        print(f"等待 memory 异步写入 {wait_sec:.1f}s …")
        time.sleep(wait_sec)

    _log_section("Step 4 · Life 热日志 / Chronicle")
    hot = soul.query_life_hot(hours=24)
    print(f"hot_storage count = {len(hot)}")
    for row in hot[:5]:
        if isinstance(row, dict):
            print(f"  · {row.get('source', '?')} turn={row.get('turn_index', '?')} {_snippet(str(row.get('content', row)))}")

    chronicle = soul.query_life_chronicle(days=3, tail=8)
    print(f"chronicle count = {len(chronicle)}")
    for row in chronicle[:5]:
        if isinstance(row, dict):
            print(f"  · {row.get('kind', '?')} {_snippet(str(row.get('summary', row)))}")

    _log_section("Step 5 · Memory 检索（recent / semantic / recall）")
    recent = soul.search_memory(mode="recent", top_k=5)
    print(f"search recent → count={recent.get('count', 0)}")
    for item in (recent.get("results") or [])[:5]:
        if isinstance(item, dict):
            print(f"  · [{item.get('id', '?')}] {_snippet(str(item.get('fact') or item.get('text') or item))}")

    semantic = soul.search_memory(
        mode="semantic",
        query="跨组评审 意外变故",
        top_k=5,
    )
    print(f"search semantic → count={semantic.get('count', 0)}")
    for item in (semantic.get("results") or [])[:5]:
        if isinstance(item, dict):
            print(f"  · [{item.get('id', '?')}] score={item.get('score', '?')} {_snippet(str(item.get('fact') or item))}")

    recall = soul.recall_memory("评审 久久不能平静", top_k=3)
    recall_text = str(recall.get("text") or "").strip()
    print(f"recall text ({len(recall_text)} chars):")
    print(_snippet(recall_text, limit=600) if recall_text else "  （空）")

    _log_section("Step 6 · Speak compose 检索注入预览")
    speak = soul._ensure_speak_service()
    probe_user = "请结合你记得的评审经历，简短回应我。"
    bundle = speak._compose_bundle(session_id, probe_user, mode="inbound")
    system = bundle.build_system()
    print(f"compose.system chars = {len(system)}")
    markers = (
        "【人物画像】",
        "【自我认知】",
        "【当前态·状态】",
        "【当前对话·压缩】",
        "【可能相关的记忆】",
    )
    for tag in markers:
        print(f"  {tag} → {'Y' if tag in system else 'N'}")
    if bundle.injected.status.similar_memories:
        print(f"similar_memories≈{_snippet(bundle.injected.status.similar_memories)}")
    if bundle.dialogue_compressed:
        print(f"dialogue_compressed≈{_snippet(bundle.dialogue_compressed)}")
    activated = bundle.meta.get("activated_memory_ids") or []
    if activated:
        print(f"activated_memory_ids = {activated}")

    _log_section("完成")
    soul.stop()
    print(f"数据目录 = {work_root}")


# ── 入口 ─────────────────────────────────────────────────────────────────────

def _run() -> None:
    from config.llm_core.config import LLMConfig
    from infra.llm import LLM, LLMHandle
    from langchain_core.messages import HumanMessage, SystemMessage

    ns = _parse_args()
    cfg_path = (ns.cfg or "").strip()
    if not cfg_path:
        sys.stderr.write(
            "用法: conda run -n LLMs python test.py <llm.yaml> [--mode MODE] [--goal \"...\"]\n"
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

    sandbox_mgr, restore_tao = (None, None)
    if ns.mode in ("full", "single"):
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
        if ns.mode == "persona-drift":
            _run_persona_drift(ns, llm_yaml)
        elif ns.mode == "soul-evolution":
            _run_soul_evolution(ns, llm_yaml, core)
        elif ns.mode == "single":
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
