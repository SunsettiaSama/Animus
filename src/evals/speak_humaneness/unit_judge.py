from __future__ import annotations

"""导演注入判定器（dynsched_llm / combo / combo_v2 臂）。

- v1（dynsched_llm / combo 臂）：只见对话近况 + 候选材料。早期版本带"宁缺毋滥"
  倾向，后被归因为画像保真度受损的原因之一，保留原文仅作对照。
- v2（combo_v2 臂）：新导演——① 喂入编剧线程产出的剧情材料做剧情对齐；
  ② prompt 以"注入该 unit 对角色本轮交互的影响"为核心，逐类写明双向影响，
  不预设注入/拒绝的默认立场。

设计输入（来自评测结论）：
- 待分享/记忆卡是角色自我暴露、人格传达的主载体，一刀切拒绝会让人格崩塌；
- 记忆候选里混有干扰条目；分享可能打断当前场景。
"""

from infra.llm import BaseLLM
from infra.llm.llm import HumanMessage, SystemMessage

from .portrait import _parse_json_object
from .think import StripsThinkLLM

_JUDGE_SYSTEM_V1 = """你是 speak 管线的导演，负责决定本轮给角色注入哪些一次性材料。判定原则：
1. 记忆用于精准共情，但候选里常混有与对方当前消息无关的干扰条目——只保留真正相关的。
2. 待分享事项是角色自己想聊的事：只有当对方的语境有承接空间（话题相通、情绪合适）时才注入；不是每轮都要分享。
3. 两类材料都可以全部拒绝；拒绝不是错误，宁缺毋滥。
只依据【对话近况】与【对方当前消息】判定。只输出一行 JSON：
{"memory_keep":[保留的候选序号，整数],"share_keep":[保留的候选序号，整数],"reason":"一句话理由"}"""

_JUDGE_SYSTEM_V2 = """你是 speak 管线的导演，负责决定本轮给角色注入哪些一次性材料。
你会同时看到编剧线程产出的【当前剧情】与【对话近况】；判定核心是：注入某个材料会对角色这一轮的交互产生什么影响。

各类材料的影响是双向的（这是权衡，不是倾向）：
- 记忆：注入后，角色能精准接住对方之前说过的事，回复更贴心、更有连续性；代价是角色的注意力可能被拉回旧事，当前剧情的沉浸感下降，若该条记忆与当下话题无关还会造成干扰。
- 待分享：注入后，角色会主动聊起自己想分享的事，为对方带来新鲜感、也让角色更像有自己生活的真人；代价是可能打断当前场景的节奏或话题的连续性。

请结合【当前剧情】与【对方当前消息】逐条判断：这一轮注入它，利与弊各自落在哪边。
注入与否没有默认答案——全注入、全不注入、部分注入都是正常决策；不要为了安全而偏向任何一边。
只输出一行 JSON：
{"memory_keep":[保留的候选序号，整数],"share_keep":[保留的候选序号，整数],"reason":"一句话理由"}"""


class LLMUnitJudge:
    def __init__(self, llm: BaseLLM, *, variant: str = "v1") -> None:
        if variant not in {"v1", "v2"}:
            raise ValueError(f"unknown judge variant: {variant!r}")
        self._llm = StripsThinkLLM(llm) if not isinstance(llm, StripsThinkLLM) else llm
        self._system = _JUDGE_SYSTEM_V1 if variant == "v1" else _JUDGE_SYSTEM_V2
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
