from __future__ import annotations

"""导演注入门控（unit gate）：编剧提案、导演判定。

拟人度评测（R2~R5）结论的生产化：
- 待分享/记忆卡是角色自我暴露、人格传达的主载体，一刀切拒绝会让人格崩塌；
- 但混入的干扰记忆会拉低回复贴合度，无关的分享会打断当前场景。

职责边界：编剧仍在剧情流里写材料调度提案（inject_memory/memory_unit_ids/
inject_share/share_indices）；本门控在编剧异步写线内对提案做逐条复核，
把最终调度写回剧情流。角色热路径只读剧情流，不含 LLM 调用——线程隔离。

两版判定器（评测中的 rd_dynsched_llm / rd_combo_v2）：
- v1：只见对话近况与候选材料，判定 prompt 偏"宁缺毋滥"——产出更松弛，
  盲测友好（评测综合 0.722，全场第一的 rd_combo 即 v1 判定）。
- v2：额外喂入编剧剧情材料做对齐，prompt 以"注入该 unit 对本轮交互的
  影响"为核心、双向权衡、不预设立场——人格/风格传达更强（风格 4.0/5）。
"""

import json
import logging
import re
from typing import Any, Callable, Iterable, Literal

logger = logging.getLogger(__name__)

UnitGateVariant = Literal["off", "v1", "v2"]

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

_GATE_SYSTEM_V1 = """你是 speak 管线的导演，负责复核本轮给角色注入哪些一次性材料。判定原则：
1. 记忆用于精准共情，但候选里常混有与对方当前消息无关的干扰条目——只保留真正相关的。
2. 待分享事项是角色自己想聊的事：只有当对方的语境有承接空间（话题相通、情绪合适）时才注入；不是每轮都要分享。
3. 两类材料都可以全部拒绝；拒绝不是错误，宁缺毋滥。
只依据【对话近况】与【对方当前消息】判定。只输出一行 JSON：
{"memory_keep":[保留的候选序号，整数],"share_keep":[保留的候选序号，整数],"reason":"一句话理由"}"""

_GATE_SYSTEM_V2 = """你是 speak 管线的导演，负责复核本轮给角色注入哪些一次性材料。
你会同时看到编剧线程产出的【当前剧情】与【对话近况】；判定核心是：注入某个材料会对角色这一轮的交互产生什么影响。

各类材料的影响是双向的（这是权衡，不是倾向）：
- 记忆：注入后，角色能精准接住对方之前说过的事，回复更贴心、更有连续性；代价是角色的注意力可能被拉回旧事，当前剧情的沉浸感下降，若该条记忆与当下话题无关还会造成干扰。
- 待分享：注入后，角色会主动聊起自己想分享的事，为对方带来新鲜感、也让角色更像有自己生活的真人；代价是可能打断当前场景的节奏或话题的连续性。

请结合【当前剧情】与【对方当前消息】逐条判断：这一轮注入它，利与弊各自落在哪边。
注入与否没有默认答案——全注入、全不注入、部分注入都是正常决策；不要为了安全而偏向任何一边。
只输出一行 JSON：
{"memory_keep":[保留的候选序号，整数],"share_keep":[保留的候选序号，整数],"reason":"一句话理由"}"""


def resolve_unit_gate_variant(value: object) -> UnitGateVariant:
    normalized = str(value or "").strip().lower()
    if normalized in {"v1", "1"}:
        return "v1"
    if normalized in {"v2", "2"}:
        return "v2"
    return "off"


class UnitGateDirector:
    """注入门控导演。装配于 `_bind_director_system`，随编剧异步写线调用。"""

    def __init__(
        self,
        llm: Any | None,
        *,
        variant: UnitGateVariant,
        max_candidates: int = 8,
    ) -> None:
        if variant not in ("v1", "v2"):
            raise ValueError(f"unit gate variant must be v1/v2, got {variant!r}")
        self._llm = llm
        self._variant: UnitGateVariant = variant
        self._max_candidates = max(1, int(max_candidates))
        self._cache: dict[tuple, tuple[tuple[int, ...], tuple[int, ...]]] = {}
        self.calls = 0
        self.errors = 0

    @property
    def variant(self) -> UnitGateVariant:
        return self._variant

    def filter_schedule(
        self,
        *,
        session_id: str = "",
        user_text: str,
        frame_text: str,
        plot_context: str,
        memory_texts: tuple[str, ...] | list[str],
        share_texts: tuple[str, ...] | list[str],
        memory_unit_ids: tuple[str, ...] | list[str],
        share_indices: tuple[int, ...] | list[int],
    ) -> dict[str, Any] | None:
        """对编剧提案做逐条复核。

        返回最终调度 dict（inject_memory/memory_unit_ids/inject_share/
        share_indices/reason）；判定失败（LLM 不可用/解析失败/异常）返回
        None——调用方保持编剧原提案，绝不因门控故障而清空材料。
        """
        mem_texts = tuple(str(t).strip() for t in memory_texts if str(t).strip())
        shr_texts = tuple(str(t).strip() for t in share_texts if str(t).strip())
        if not mem_texts and not shr_texts:
            return None
        if self._llm is None:
            return None
        key = (user_text, frame_text, plot_context, mem_texts, shr_texts)
        cached = self._cache.get(key)
        if cached is not None:
            keep_mem, keep_share = cached
        else:
            verdict = self._judge(
                session_id=session_id,
                user_text=user_text,
                frame_text=frame_text,
                plot_context=plot_context,
                memory_texts=mem_texts,
                share_texts=shr_texts,
            )
            if verdict is None:
                self.errors += 1
                return None
            keep_mem, keep_share = verdict
            self._cache[key] = verdict
            if len(self._cache) > 512:
                self._cache.pop(next(iter(self._cache)))

        ids = [str(x).strip() for x in memory_unit_ids if str(x).strip()]
        if not ids:
            ids = [f"mem-{i}" for i in range(len(mem_texts))]
        gated_mem_ids = [ids[i] for i in keep_mem if 0 <= i < len(ids)]

        idx = [int(x) for x in share_indices if str(x).lstrip("-").isdigit()]
        if not idx:
            idx = list(range(len(shr_texts)))
        gated_share_idx = [idx[i] for i in keep_share if 0 <= i < len(idx)]

        return {
            "inject_memory": bool(gated_mem_ids),
            "memory_unit_ids": gated_mem_ids,
            "inject_share": bool(gated_share_idx),
            "share_indices": gated_share_idx,
            "reason": f"unit_gate:{self._variant}",
        }

    def _judge(
        self,
        *,
        session_id: str = "",
        user_text: str,
        frame_text: str,
        plot_context: str,
        memory_texts: tuple[str, ...],
        share_texts: tuple[str, ...],
    ) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
        system = _GATE_SYSTEM_V1 if self._variant == "v1" else _GATE_SYSTEM_V2
        lines: list[str] = []
        if self._variant == "v2" and plot_context.strip():
            lines.append(f"【当前剧情】\n{plot_context.strip()}")
        if frame_text.strip():
            lines.append(f"【对话近况】\n{frame_text.strip()}")
        lines.append(f"【对方当前消息】\n{user_text.strip() or '（对方未发言）'}")
        if memory_texts:
            listed = "\n".join(
                f"{i}. {t[:160]}" for i, t in enumerate(memory_texts[: self._max_candidates])
            )
            lines.append(f"【候选记忆】\n{listed}")
        else:
            lines.append("【候选记忆】\n（无）")
        if share_texts:
            listed = "\n".join(
                f"{i}. {t[:160]}" for i, t in enumerate(share_texts[: self._max_candidates])
            )
            lines.append(f"【候选待分享】\n{listed}")
        else:
            lines.append("【候选待分享】\n（无）")
        try:
            raw = self._llm.generate_json(
                system=system,
                user="\n\n".join(lines),
                session_id=session_id,
                director=f"unit_gate_{self._variant}",
            )
        except Exception as exc:  # noqa: BLE001 - 门控故障回退编剧提案
            logger.warning("unit gate llm call failed (%s): %s", self._variant, exc)
            return None
        self.calls += 1
        payload = _parse_json(raw)
        if payload is None:
            return None
        return (_int_list(payload.get("memory_keep")), _int_list(payload.get("share_keep")))


def _parse_json(raw: object) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    match = _JSON_OBJECT.search(text)
    if match is None:
        return None
    try:
        payload = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


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


MaterialGate = Callable[..., dict[str, Any] | None]
