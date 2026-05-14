from __future__ import annotations

from typing import Any, Mapping

from .components.node_spec import NodeManifest
from .components.observation import TaoStep
from .components.atomic_planner import LlmCallFn
from .registry import NodeRegistry, get_registry


def _build_llm_call(llm_cfg_path: str) -> LlmCallFn:
    """接线层：将 flow/planner._build_tao_loop 包装为 base 层可用的 LlmCallFn。

    base/components/ 的 AtomicPlanner / AtomicReviewer 不直接依赖 TaoLoop；
    此函数是唯一跨越 base → flow 边界的点，集中于 defaults.py（接线层）。
    """
    from agent.flow.planner import _build_tao_loop
    from agent.flow.config import PlannerConfig
    from agent.react.tao import FinishEvent

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
    1. 从 manifest 读取 tool_package / max_steps / system_note，构造 SubAgentProfile。
    2. 将 manifest.description + 上游 inputs + ctx.corrections 拼装为 instruction。
    3. 调用 SubAgentRunner.run_sync()，通过 event_callback 把 StepEvent 转换为
       TaoStep 并上报给 ctx.on_step（供 RunnableNode 收集观察链）。
    4. 返回 answer 字符串。
    """

    def __init__(self, llm_cfg_path: str) -> None:
        self._llm_cfg_path = llm_cfg_path

    def run(
        self,
        manifest: NodeManifest,
        inputs: Mapping[str, Any],
        ctx: Any = None,
    ) -> Any:
        from agent.profile import SubAgentProfile
        from agent.runner import SubAgentRunner
        from agent.react.tao import StepEvent

        profile = SubAgentProfile(
            max_steps=manifest.max_steps or 10,
            tool_package=manifest.tool_package,
            system_note=manifest.system_note,
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
        )
        return result.get("answer", "")


def register_defaults(
    llm_cfg_path: str,
    registry: NodeRegistry | None = None,
) -> None:
    """向 NodeRegistry 注入默认执行器工厂与全部内置工具包。

    Parameters
    ----------
    llm_cfg_path:
        LLM 配置文件路径，与 FlowConfig.llm_cfg_path 保持一致。
    registry:
        目标注册表；为 None 时使用全局单例。

    注意
    ----
    · 执行器工厂对所有 tool_package 均返回同一 SubAgentManifestExecutor 实例；
      executor 会在 run() 时从 manifest.tool_package 读取包名并传给 SubAgentProfile。
    · Verifier 工厂不注册，RunnableNode 会以 VerificationResult.skip() 兜底。
      若需要具体 verifier，在调用本函数后再调用 registry.set_verifier_factory()。
    """
    from agent.react.action.manager import BUILTIN_PACKAGES
    from agent.flow.base.components.atomic_planner import AtomicPlanner
    from agent.flow.base.components.atomic_reviewer import AtomicReviewer

    reg = registry or get_registry()
    _executor = SubAgentManifestExecutor(llm_cfg_path)
    reg.set_executor_factory(lambda _pkg: _executor)
    reg.register_packages(*(pkg.name for pkg in BUILTIN_PACKAGES))

    # AtomicPlanner factory：构建时同步注入 AtomicReviewer
    def _build_planner(cfg_path: str) -> AtomicPlanner:
        llm_call = _build_llm_call(cfg_path)
        reviewer  = AtomicReviewer(llm_call)
        return AtomicPlanner(llm_call, reviewer=reviewer)

    reg.set_atomic_planner_factory(_build_planner)
    reg.set_atomic_reviewer_factory(
        lambda cfg_path: AtomicReviewer(_build_llm_call(cfg_path))
    )
