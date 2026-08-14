from __future__ import annotations

import dataclasses
from typing import Any, Mapping

from .components.node_spec import NodeManifest
from .components.observation import TaoStep
from .components.atomic_planner import LlmCallFn
from .registry import NodeRegistry, get_registry


def _build_llm_call(llm_cfg_path: str) -> LlmCallFn:
    """后备接线：仅在调用方未注入 LlmCallFn 时使用，通过 flow.planner._build_tao_loop 构造。

    若调用方在 register_defaults(llm_cfg_path, llm_call_fn=my_fn) 时直接传入
    LlmCallFn，则此函数不会被调用，base 层对 agent.flow.cluster.planner 零依赖。
    """
    from worker.flow.cluster.planner import _build_tao_loop
    from worker.flow.cluster.config import PlannerConfig
    from worker.engine.tao import FinishEvent

    cfg = PlannerConfig()

    def _call(system_prompt: str, user_prompt: str) -> str:
        tao = _build_tao_loop(cfg, llm_cfg_path, system_prompt)
        answer = ""
        for event in tao.stream(user_prompt):
            if isinstance(event, FinishEvent):
                answer = event.answer
        return answer

    return _call


class SubAgentManifestExecutor:
    """将 SubAgentRunner 包装为 ManifestExecutor 协议。

    执行流程
    --------
    1. 从 manifest 读取 capability_card_id / max_steps / system_note，构造 SubAgentProfile。
    2. 将 manifest.description + 上游 inputs + ctx.corrections 拼装为 instruction。
    3. 调用 SubAgentRunner.run_sync()，通过 event_callback 把 StepEvent 转换为
       TaoStep 并上报给 ctx.on_step（供 RunnableNode 收集观察链）。
    4. 返回 answer 字符串。
    """

    def __init__(
        self,
        llm_cfg_path: str,
        *,
        agent_state_service: Any = None,
    ) -> None:
        self._llm_cfg_path = llm_cfg_path
        self._agent_state_service = agent_state_service

    def run(
        self,
        manifest: NodeManifest,
        inputs: Mapping[str, Any],
        ctx: Any = None,
    ) -> Any:
        from worker.cards import materialize_capability
        from worker.runner import SubAgentRunner
        from worker.engine.tao import StepEvent

        card_id = manifest.capability_card_id or "minimal"
        profile = materialize_capability(card_id)
        profile = dataclasses.replace(
            profile,
            max_steps=manifest.max_steps or profile.max_steps,
            system_note=manifest.system_note or profile.system_note,
        )

        instruction = manifest.description
        if inputs:
            ctx_lines = "\n".join(f"{k}: {v}" for k, v in inputs.items())
            instruction = f"{instruction}\n\nContext:\n{ctx_lines}"
        if ctx and ctx.corrections:
            fixes = "\n".join(f"- {c}" for c in ctx.corrections)
            instruction += f"\n\nFix the following issues:\n{fixes}"

        def _on_event(event: Any) -> None:
            if ctx and ctx.on_step and isinstance(event, StepEvent):
                ctx.on_step(TaoStep(
                    index=event.index,
                    thought=event.thought or "",
                    action=event.action or "",
                    action_input=None,
                    observation=event.observation or "",
                ))

        result = SubAgentRunner().run_sync(
            instruction,
            profile,
            self._llm_cfg_path,
            event_callback=_on_event,
            agent_state_service=self._agent_state_service,
        )
        return result.get("answer", "")


def register_defaults(
    llm_cfg_path: str,
    registry: NodeRegistry | None = None,
    *,
    llm_call_fn: LlmCallFn | None = None,
    agent_state_service: Any = None,
) -> None:
    """向 NodeRegistry 注入默认执行器工厂与全部内置能力卡。

    Parameters
    ----------
    llm_cfg_path:
        LLM 配置文件路径，与 FlowConfig.llm_cfg_path 保持一致。
    registry:
        目标注册表；为 None 时使用全局单例。
    llm_call_fn:
        可选的 LlmCallFn 注入。提供后 AtomicPlanner / AtomicReviewer 直接使用，
        base 层对 agent.flow.cluster.planner 完全零依赖；
        不提供时退回 _build_llm_call(llm_cfg_path)（仍依赖 flow.planner）。

    注意
    ----
    · 执行器工厂对所有 capability_card_id 均返回同一 SubAgentManifestExecutor 实例；
      executor 会在 run() 时从 manifest.capability_card_id 物化 SubAgentProfile。
    · Verifier 工厂不注册，RunnableNode 会以 VerificationResult.skip() 兜底。
      若需要具体 verifier，在调用本函数后再调用 registry.set_verifier_factory()。
    """
    from worker.cards import get_card_registry
    from worker.flow.base.components.atomic_planner import AtomicPlanner
    from worker.flow.base.components.atomic_reviewer import AtomicReviewer

    reg = registry or get_registry()
    _executor = SubAgentManifestExecutor(
        llm_cfg_path,
        agent_state_service=agent_state_service,
    )
    reg.set_executor_factory(lambda _card_id: _executor)
    reg.register_cards(*get_card_registry().ids())

    def _resolve_llm_call(cfg_path: str) -> LlmCallFn:
        return llm_call_fn if llm_call_fn is not None else _build_llm_call(cfg_path)

    def _build_planner(cfg_path: str) -> AtomicPlanner:
        llm_call = _resolve_llm_call(cfg_path)
        reviewer = AtomicReviewer(llm_call)
        return AtomicPlanner(llm_call, reviewer=reviewer)

    reg.set_atomic_planner_factory(_build_planner)
    reg.set_atomic_reviewer_factory(
        lambda cfg_path: AtomicReviewer(_resolve_llm_call(cfg_path))
    )
