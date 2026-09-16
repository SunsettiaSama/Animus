from __future__ import annotations

"""dynsched_llm 臂的导演注入判定器：带对话语境逐轮判定记忆/分享注入。

设计输入（来自评测结论）：
- 记忆能带来精准共情，但候选里混有干扰条目 → 逐条判相关；
- 待分享事项是角色自己想聊的事，对方语境有承接空间才注入，不是每轮都分享；
- 全部拒绝是合法决策。
"""

from infra.llm import BaseLLM
from infra.llm.llm import HumanMessage, SystemMessage

from .portrait import _parse_json_object
from .think import StripsThinkLLM

_JUDGE_SYSTEM = """你是 speak 管线的导演，负责决定本轮给角色注入哪些一次性材料。判定原则：
1. 记忆用于精准共情，但候选里常混有与对方当前消息无关的干扰条目——只保留真正相关的。
2. 待分享事项是角色自己想聊的事：只有当对方的语境有承接空间（话题相通、情绪合适）时才注入；不是每轮都要分享。
3. 两类材料都可以全部拒绝；拒绝不是错误，宁缺毋滥。
只依据【对话近况】与【对方当前消息】判定。只输出一行 JSON：
{"memory_keep":[保留的候选序号，整数],"share_keep":[保留的候选序号，整数],"reason":"一句话理由"}"""


class LLMUnitJudge:
    def __init__(self, llm: BaseLLM) -> None:
        self._llm = StripsThinkLLM(llm) if not isinstance(llm, StripsThinkLLM) else llm
        self._cache: dict[tuple, tuple[tuple[int, ...], tuple[int, ...]]] = {}
        self.calls = 0

    def judge(
        self,
        session_id: str,
        user_text: str,
        frame_text: str,
        memory_texts: tuple[str, ...],
        share_texts: tuple[str, ...],
    ) -> tuple[tuple[int, ...], tuple[int, ...]]:
        candidates = (tuple(memory_texts), tuple(share_texts))
        if not any(candidates[0]) and not any(candidates[1]):
            return (), ()
        key = (session_id, user_text, candidates)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        lines = []
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
                SystemMessage(content=_JUDGE_SYSTEM),
                HumanMessage(content="\n\n".join(lines)),
            ]
        )
        payload = _parse_json_object(raw)
        keep_mem = _int_list(payload.get("memory_keep"))
        keep_share = _int_list(payload.get("share_keep"))
        if not payload:
            # 评委输出不可解析：保守全拒（宁缺毋滥），不注入干扰材料
            keep_mem, keep_share = (), ()
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
