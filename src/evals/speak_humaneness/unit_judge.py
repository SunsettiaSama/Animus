from __future__ import annotations

"""导演注入判定器（dynsched_llm / combo / combo_v2 臂）。

判定 prompt 与生产 `directors/unit_gate.py` 单源共享（import 而非拷贝），
评测与生产永不漂移。评测侧差异仅在于：LLM 调用走 BaseLLM 评测实例
（生产走 DirectorLLMCaller）。

- v1（dynsched_llm / combo 臂）：只见对话近况 + 候选材料，偏"宁缺毋滥"
  （评测综合 0.722 的 rd_combo 即 v1 判定）。
- v2（combo_v2 臂）：新导演——喂入编剧线程产出的剧情材料做对齐；
  prompt 以"注入该 unit 对角色本轮交互的影响"为核心，双向权衡、
  不预设注入/拒绝的默认立场。
"""

from agent.soul.speak.responders.request_driven.directors.unit_gate import (
    _GATE_SYSTEM_V1,
    _GATE_SYSTEM_V2,
)
from infra.llm import BaseLLM
from infra.llm.llm import HumanMessage, SystemMessage

from .portrait import _parse_json_object
from .think import StripsThinkLLM


class LLMUnitJudge:
    def __init__(self, llm: BaseLLM, *, variant: str = "v1") -> None:
        if variant not in {"v1", "v2"}:
            raise ValueError(f"unknown judge variant: {variant!r}")
        self._llm = StripsThinkLLM(llm) if not isinstance(llm, StripsThinkLLM) else llm
        self._system = _GATE_SYSTEM_V1 if variant == "v1" else _GATE_SYSTEM_V2
        self._with_plot = variant == "v2"
        self._cache: dict[tuple, tuple[tuple[int, ...], tuple[int, ...]]] = {}
        self.calls = 0

    def judge(
        self,
        session_id: str,
        user_text: str,
        frame_text: str,
        memory_texts: tuple[str, ...],
        share_texts: tuple[str, ...],
        plot_context: str = "",
    ) -> tuple[tuple[int, ...], tuple[int, ...]]:
        candidates = (tuple(memory_texts), tuple(share_texts))
        if not any(candidates[0]) and not any(candidates[1]):
            return (), ()
        key = (session_id, user_text, candidates, plot_context if self._with_plot else "")
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        lines = []
        if self._with_plot and plot_context.strip():
            lines.append(f"【当前剧情】\n{plot_context.strip()}")
        if frame_text.strip():
            lines.append(f"【对话近况】\n{frame_text.strip()}")
        lines.append(f"【对方当前消息】\n{user_text.strip()}")
        if any(candidates[0]):
            listed = "\n".join(f"{i}. {t}" for i, t in enumerate(candidates[0]))
            lines.append(f"【候选记忆】\n{listed}")
        else:
            lines.append("【候选记忆】\n（无）")
        if any(candidates[1]):
            listed = "\n".join(f"{i}. {t}" for i, t in enumerate(candidates[1]))
            lines.append(f"【候选待分享】\n{listed}")
        else:
            lines.append("【候选待分享】\n（无）")
        raw = self._llm.generate_messages(
            [
                SystemMessage(content=self._system),
                HumanMessage(content="\n\n".join(lines)),
            ]
        )
        payload = _parse_json_object(raw)
        if not payload:
            # 评委输出不可解析时的兜底：保持候选原样全保留，而非全部拒绝
            # （拒绝会把人格载体清空，v1 实测证明该兜底代价更高）
            keep_mem = tuple(range(len(candidates[0])))
            keep_share = tuple(range(len(candidates[1])))
        else:
            keep_mem = _int_list(payload.get("memory_keep"))
            keep_share = _int_list(payload.get("share_keep"))
        verdict = (keep_mem, keep_share)
        self._cache[key] = verdict
        self.calls += 1
        return verdict


def _int_list(value: object) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    out: list[int] = []
    for item in value:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return tuple(out)
