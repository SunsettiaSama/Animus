from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from ..directors.base import DirectorLLMCaller, extract_json_object
from .materials import WritingMaterials
from .scene_seed import is_usable_scene_seed

_MAX_REACT_STEPS = 6
_TARGET_UNITS = 10
_MIN_LOOKS_BEFORE_NUDGE = 2
_LOOKS = frozenset(
    {
        "look_interaction",
        "look_memory",
        "look_share",
        "look_seeds",
        "look_fate_panel",
        "look_scene",
    }
)
_PRODUCE_OUTLINE = "produce_outline"
_PRODUCE_PLOT = "produce_plot"
_ALLOWED_INIT = _LOOKS | {_PRODUCE_OUTLINE}
_ALLOWED_ALIGN = _LOOKS | {_PRODUCE_PLOT}


@dataclass
class ScreenwriterAgentTrace:
    """编剧 agent 一步观察记录。"""

    think: str = ""
    action: str = ""
    observation: str = ""

    def snapshot(self) -> dict[str, Any]:
        return {
            "think": self.think,
            "action": self.action,
            "observation": self.observation[:400],
        }


@dataclass
class ScreenwriterAgentResult:
    payload: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    used_fallback: bool = False
    steps: tuple[ScreenwriterAgentTrace, ...] = ()
    lookups: tuple[str, ...] = ()

    def snapshot(self) -> dict[str, Any]:
        return {
            "payload": dict(self.payload),
            "reason": self.reason,
            "used_fallback": self.used_fallback,
            "steps": [s.snapshot() for s in self.steps],
            "lookups": list(self.lookups),
        }


class ScreenwriterAgent:
    """编剧：先写大纲，再并行写开场旁白与初始剧情 unit。"""

    name = "screenwriter_agent"

    _SYSTEM_LOOK_OUTLINE = (
        "你是叙事编剧。先写本场大纲。\n"
        "先查阅材料，再交大纲。这次只写大纲，不写开场旁白，也不写逐步 unit。\n"
        "大纲是一条完整故事线：起因 → 经过 → 转折或发现 → 收束可能。"
        "写清楚这场从哪开始、中间会遇到什么、往哪个方向落；"
        "要能撑住后续大约十个执行步骤，而不是两三件待办事项。\n"
        "文风客观、冷静、真实。用第三人称或动宾叙述，写可核验的场面事实与因果。"
        "不抒情，不说教，不用「你看见……」这类旁白，不写角色台词。\n"
        "交互记录优先参考：写交互如何发生、对角色后续故事线有什么影响。"
        "记忆、分享、抽词种子、场面与临场状态按需要取用，嵌进故事线里，不要罗列堆砌。\n"
        "每一步选一个动作：\n"
        "- look_interaction｜交互记录\n"
        "- look_memory｜记忆\n"
        "- look_share｜想分享的话头\n"
        "- look_seeds｜抽词种子\n"
        "- look_fate_panel｜开口欲与临场状态\n"
        "- look_scene｜场面与人格\n"
        "- produce_outline｜交大纲\n"
        "交大纲时写：\n"
        "1) plot_arc.summary 完整故事线（一段连贯叙述，含始末与中间节点）；\n"
        "2) plot_arc.evidence 依据（材料里已有的事实）；\n"
        "3) side 短标签（mood/brief 等，不放进故事线正文）。\n"
        "每步输出 JSON："
        '{"think":"…","action":"look_interaction|look_memory|look_share|look_seeds|'
        'look_fate_panel|look_scene|produce_outline",'
        '"plot_arc":{"summary":"…","evidence":"…"},'
        '"side":{"mood":"…","brief":"…","user_identity":"…","user_activity":"…"},'
        '"reason":"…"}'
    )

    _SYSTEM_OPENING = (
        "你是叙事编剧。大纲已经写完。接下来写开场旁白，给用户看。\n"
        "开场旁白走 outline 的投递渠道，只面向用户。不要写角色台词，"
        "也不要把大纲或场记塞进旁白里。\n"
        "写眼前能看到的东西，比如「你看见她……」。"
        "「你」表示观看位置；角色的动作写她或他。\n"
        "入镜的内容包括物件、光线、位置、手头正做的事。一到两句，只交这一份。"
        "旁白是开场镜头，不是整场故事线；故事线以已写的大纲为准。\n"
        "输出 JSON："
        '{"opening":"…","reason":"…"}'
    )

    _SYSTEM_UNITS = (
        "你是叙事编剧。大纲已经写完。接下来把大纲拆成初始剧情 unit。\n"
        f"写大约 {_TARGET_UNITS} 个角色步骤，按顺序覆盖大纲故事线的起因→经过→转折→收束，"
        "不要写成互不相关的零散动作。\n"
        "intent 用动宾短句，主语是角色；写客观、可执行的内容。\n"
        "需要时带上 memory_unit_ids 或 share_indices，把材料续进戏里。\n"
        "输出 JSON："
        '{"plot_arc":{"units":[{"intent":"…","evidence":"…","span_polls":2}]},'
        '"inject_memory":true,"memory_unit_ids":[],'
        '"inject_share":false,"share_indices":[],'
        '"reason":"…"}'
    )

    _SYSTEM_ALIGN = (
        "你是叙事编剧。用户和角色已经来回了几轮，后续的剧情 unit 可能偏了，需要对齐。\n"
        "先查阅材料，再交对齐后的内容。这次交的是对齐后的完整故事线和后续步骤。\n"
        "大纲仍然是一条完整故事线（起因→经过→转折→收束），"
        "文风客观、冷静、真实。可以根据交互核对后微调，但不要缩成待办列表，也不要写成旁白。\n"
        "当前正在执行的步骤会保留，不要重写它；"
        "后续 unit 按完整故事线接上角色的注意点和手头活计。\n"
        "交互记录优先参考：写交互如何发生、对角色后续故事线有什么影响，不写角色台词。"
        "记忆、分享、抽词种子、场面与临场状态按需要取用。\n"
        "每一步选一个动作：\n"
        "- look_interaction｜交互记录\n"
        "- look_memory｜记忆\n"
        "- look_share｜想分享的话头\n"
        "- look_seeds｜抽词种子\n"
        "- look_fate_panel｜开口欲与临场状态\n"
        "- look_scene｜场面与人格\n"
        "- produce_plot｜交对齐后的后续步骤\n"
        "交稿时写：\n"
        "1) plot_arc.summary 完整故事线（可以沿用或按交互微调）；\n"
        f"2) plot_arc.units 大约 {_TARGET_UNITS} 个后续角色步骤（动宾短句，覆盖故事线剩下的段落）；\n"
        "3) plot_flow 场记（chronicle / interaction_process / focus_now / next_push / beat）；"
        "interaction_process 写交互如何发生、对角色后续的影响，不写角色台词；\n"
        "4) 需要时带上 memory_unit_ids 或 share_indices。\n"
        "每步输出 JSON："
        '{"think":"…","action":"look_interaction|look_memory|look_share|look_seeds|'
        'look_fate_panel|look_scene|produce_plot",'
        '"plot_arc":{"summary":"…","evidence":"…","units":[{"intent":"…","span_polls":2}]},'
        '"plot_flow":{"chronicle":"…","interaction_process":"…","focus_now":"…","beat":"…","beat_kind":"push"},'
        '"side":{"mood":"…","brief":"…","user_identity":"…","user_activity":"…"},'
        '"inject_memory":true,"memory_unit_ids":[],"inject_share":false,"share_indices":[],'
        '"reason":"…"}'
    )
    
    def __init__(
        self,
        llm: DirectorLLMCaller | None = None,
        *,
        max_steps: int = _MAX_REACT_STEPS,
        target_units: int = _TARGET_UNITS,
    ) -> None:
        self._llm = llm
        self._max_steps = max(2, int(max_steps))
        self._target_units = max(4, int(target_units))

    def compose(
        self,
        materials: WritingMaterials,
        *,
        session_id: str = "",
        turn_index: int = 0,
        task: str = "init",
        previous_arc_text: str = "",
        previous_flow_text: str = "",
        on_opening_ready: Callable[[str, str], None] | None = None,
    ) -> ScreenwriterAgentResult:
        """init：先大纲，再并行开场旁白与初始 unit。align：按交互对齐后续 unit。"""
        if self._llm is None or not self._llm.available:
            return self._heuristic(materials, reason="llm_unavailable")
        if task == "init":
            return self._compose_init(
                materials,
                session_id=session_id,
                turn_index=turn_index,
                on_opening_ready=on_opening_ready,
            )
        return self._compose_align(
            materials,
            session_id=session_id,
            turn_index=turn_index,
            previous_arc_text=previous_arc_text,
            previous_flow_text=previous_flow_text,
        )

    def _compose_init(
        self,
        materials: WritingMaterials,
        *,
        session_id: str,
        turn_index: int,
        on_opening_ready: Callable[[str, str], None] | None = None,
    ) -> ScreenwriterAgentResult:
        steps, lookups, observations, outline_raw = self._look_until_produce(
            materials,
            session_id=session_id,
            turn_index=turn_index,
            task="init",
            previous_arc_text="",
            previous_flow_text="",
            produce_action=_PRODUCE_OUTLINE,
            allowed=_ALLOWED_INIT,
            system=self._SYSTEM_LOOK_OUTLINE,
            director="screenwriter_outline",
            force_hint=(
                "本步交大纲：action=produce_outline；"
                "plot_arc.summary 写完整故事线（起因→经过→转折→收束），客观冷静真实；"
                "并写好 evidence。"
            ),
            nudge_hint="材料已展开不少，可以 produce_outline 交完整故事线了。",
        )
        outline = self._extract_outline(outline_raw, materials)
        summary = str((outline.get("plot_arc") or {}).get("summary") or "").strip()
        used_fallback = False
        if not summary:
            filled = self._heuristic(materials, reason="agent_outline_empty")
            outline = self._merge_payload(outline, filled.payload)
            summary = str((outline.get("plot_arc") or {}).get("summary") or "").strip()
            used_fallback = True
        if not summary:
            return ScreenwriterAgentResult(
                payload=self._heuristic(materials, reason="agent_outline_empty").payload,
                reason="agent_outline_empty",
                used_fallback=True,
                steps=tuple(steps),
                lookups=tuple(dict.fromkeys(lookups)),
            )

        evidence = str((outline.get("plot_arc") or {}).get("evidence") or "").strip()
        steps.append(
            ScreenwriterAgentTrace(
                think=str(outline_raw.get("think") or "").strip(),
                action=_PRODUCE_OUTLINE,
                observation=_PRODUCE_OUTLINE,
            )
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_opening = pool.submit(
                self._job_opening,
                materials,
                session_id=session_id,
                turn_index=turn_index,
                summary=summary,
                evidence=evidence,
                observations=observations,
            )
            fut_units = pool.submit(
                self._job_units,
                materials,
                session_id=session_id,
                turn_index=turn_index,
                summary=summary,
                evidence=evidence,
                observations=observations,
            )
            opening_raw = fut_opening.result()
            opening = str(opening_raw.get("opening") or "").strip()
            if not opening:
                opening = self._heuristic_opening(materials, summary)
                used_fallback = True
            from .writer import normalize_user_opening

            # 用户旁白先规范化，再占用 outline 渠道投递一次
            opening = normalize_user_opening(opening)
            if on_opening_ready is not None and opening:
                on_opening_ready(session_id, opening)
            units_raw = fut_units.result()
        units = self._parse_units(units_raw.get("plot_arc") if isinstance(units_raw.get("plot_arc"), dict) else {})
        if len(units) < max(4, self._target_units // 2):
            filled = self._heuristic(materials, reason="agent_units_sparse")
            units = list((filled.payload.get("plot_arc") or {}).get("units") or [])
            used_fallback = True

        payload = self._merge_init_jobs(
            outline,
            opening=opening,
            units=units,
            units_raw=units_raw,
            materials=materials,
        )
        steps.append(
            ScreenwriterAgentTrace(
                think="",
                action="produce_opening",
                observation=opening[:360],
            )
        )
        steps.append(
            ScreenwriterAgentTrace(
                think="",
                action="produce_units",
                observation=f"units={len(units)}",
            )
        )
        return ScreenwriterAgentResult(
            payload=payload,
            reason=str(outline_raw.get("reason") or "agent_init_three_jobs"),
            used_fallback=used_fallback,
            steps=tuple(steps),
            lookups=tuple(dict.fromkeys(lookups)),
        )

    def _compose_align(
        self,
        materials: WritingMaterials,
        *,
        session_id: str,
        turn_index: int,
        previous_arc_text: str,
        previous_flow_text: str,
    ) -> ScreenwriterAgentResult:
        steps, lookups, observations, raw = self._look_until_produce(
            materials,
            session_id=session_id,
            turn_index=turn_index,
            task="align",
            previous_arc_text=previous_arc_text,
            previous_flow_text=previous_flow_text,
            produce_action=_PRODUCE_PLOT,
            allowed=_ALLOWED_ALIGN,
            system=self._SYSTEM_ALIGN,
            director="screenwriter_align",
            force_hint="本步交稿：action=produce_plot，按交互对齐后续步骤与场记。",
            nudge_hint="材料已展开不少，可以 produce_plot 对齐后续步骤了。",
        )
        if not raw:
            fallback = self._heuristic(materials, reason="agent_max_steps")
            return ScreenwriterAgentResult(
                payload=fallback.payload,
                reason="agent_max_steps_heuristic",
                used_fallback=True,
                steps=tuple(steps),
                lookups=tuple(dict.fromkeys(lookups)),
            )
        payload = self._extract_produce(raw, materials)
        payload["opening"] = ""
        steps.append(
            ScreenwriterAgentTrace(
                think=str(raw.get("think") or "").strip(),
                action=_PRODUCE_PLOT,
                observation=_PRODUCE_PLOT,
            )
        )
        units = (payload.get("plot_arc") or {}).get("units") or []
        if len(units) < max(4, self._target_units // 2):
            filled = self._heuristic(materials, reason="agent_units_sparse")
            merged = self._merge_payload(payload, filled.payload)
            merged["opening"] = ""
            return ScreenwriterAgentResult(
                payload=merged,
                reason=str(raw.get("reason") or "agent_produce_sparse_fill"),
                used_fallback=True,
                steps=tuple(steps),
                lookups=tuple(dict.fromkeys(lookups)),
            )
        return ScreenwriterAgentResult(
            payload=payload,
            reason=str(raw.get("reason") or "agent_produce_plot"),
            used_fallback=False,
            steps=tuple(steps),
            lookups=tuple(dict.fromkeys(lookups)),
        )

    def _look_until_produce(
        self,
        materials: WritingMaterials,
        *,
        session_id: str,
        turn_index: int,
        task: str,
        previous_arc_text: str,
        previous_flow_text: str,
        produce_action: str,
        allowed: frozenset[str],
        system: str,
        director: str,
        force_hint: str,
        nudge_hint: str,
    ) -> tuple[list[ScreenwriterAgentTrace], list[str], list[str], dict[str, Any]]:
        steps: list[ScreenwriterAgentTrace] = []
        lookups: list[str] = []
        observations: list[str] = []
        for step_i in range(self._max_steps):
            force_produce = step_i >= self._max_steps - 1 and bool(observations)
            raw = self._step(
                materials,
                session_id=session_id,
                turn_index=turn_index,
                task=task,
                observations=observations,
                previous_arc_text=previous_arc_text,
                previous_flow_text=previous_flow_text,
                system=system,
                director=director,
                force_produce=force_produce,
                force_hint=force_hint,
                nudge_hint=nudge_hint,
                lookup_count=len(lookups),
            )
            think = str(raw.get("think") or "").strip()
            action = str(raw.get("action") or "").strip().lower()
            if force_produce:
                action = produce_action
            elif action not in allowed:
                action = produce_action if observations else "look_interaction"
            elif (
                action != produce_action
                and action in lookups
                and len(set(lookups)) >= _MIN_LOOKS_BEFORE_NUDGE
            ):
                raw = self._step(
                    materials,
                    session_id=session_id,
                    turn_index=turn_index,
                    task=task,
                    observations=observations,
                    previous_arc_text=previous_arc_text,
                    previous_flow_text=previous_flow_text,
                    system=system,
                    director=director,
                    force_produce=True,
                    force_hint=force_hint,
                    nudge_hint=nudge_hint,
                    lookup_count=len(lookups),
                )
                think = str(raw.get("think") or think).strip()
                action = produce_action

            if action == produce_action:
                return steps, lookups, observations, raw

            obs = self._dispatch_look(action, materials)
            lookups.append(action)
            observations.append(f"{action} => {obs[:360]}")
            steps.append(
                ScreenwriterAgentTrace(think=think, action=action, observation=obs[:360])
            )
        return steps, lookups, observations, {}

    def _step(
        self,
        materials: WritingMaterials,
        *,
        session_id: str,
        turn_index: int,
        task: str,
        observations: list[str],
        previous_arc_text: str,
        previous_flow_text: str,
        system: str,
        director: str,
        force_produce: bool = False,
        force_hint: str = "",
        nudge_hint: str = "",
        lookup_count: int = 0,
    ) -> dict[str, Any]:
        assert self._llm is not None
        lines = [
            f"session={session_id}",
            f"turn={turn_index}",
            f"task={task}",
            f"约写步骤数={self._target_units}",
            "可先看交互记录，再按需要展开其它材料；材料够用就可以交稿。",
            f"材料目录：交互记录；记忆 {len(materials.memory_texts)}；"
            f"分享 {len(materials.share_texts)}；种子 {len(materials.scene_seeds)}；"
            f"临场状态；场面与人格。",
        ]
        if previous_arc_text.strip():
            lines.append(f"当前剧情弧=\n{previous_arc_text[:800]}")
        if previous_flow_text.strip():
            lines.append(f"当前场记=\n{previous_flow_text[:600]}")
        if observations:
            lines.append("已观察=\n" + "\n".join(f"- {o}" for o in observations[-8:]))
        else:
            lines.append("已观察=（尚无）")
        if force_produce:
            lines.append(force_hint)
        elif lookup_count >= _MIN_LOOKS_BEFORE_NUDGE:
            lines.append(nudge_hint)
        raw = self._llm.generate_json(
            system=system,
            user="\n".join(lines),
            session_id=session_id,
            director=director,
            turn_index=turn_index,
        )
        data = extract_json_object(raw)
        return data if isinstance(data, dict) else {}

    def _job_opening(
        self,
        materials: WritingMaterials,
        *,
        session_id: str,
        turn_index: int,
        summary: str,
        evidence: str,
        observations: list[str],
    ) -> dict[str, Any]:
        assert self._llm is not None
        lines = [
            f"session={session_id}",
            f"turn={turn_index}",
            "这一次写开场旁白。",
            f"大纲=\n{summary}",
        ]
        if evidence:
            lines.append(f"依据=\n{evidence}")
        if observations:
            lines.append("已观察=\n" + "\n".join(f"- {o}" for o in observations[-8:]))
        if materials.scene_seeds:
            lines.append("抽词种子=" + "、".join(materials.scene_seeds[:8]))
        raw = self._llm.generate_json(
            system=self._SYSTEM_OPENING,
            user="\n".join(lines),
            session_id=session_id,
            director="screenwriter_opening",
            turn_index=turn_index,
        )
        data = extract_json_object(raw)
        return data if isinstance(data, dict) else {}

    def _job_units(
        self,
        materials: WritingMaterials,
        *,
        session_id: str,
        turn_index: int,
        summary: str,
        evidence: str,
        observations: list[str],
    ) -> dict[str, Any]:
        assert self._llm is not None
        lines = [
            f"session={session_id}",
            f"turn={turn_index}",
            f"约写步骤数={self._target_units}",
            "这一次写初始剧情 unit。",
            f"大纲=\n{summary}",
        ]
        if evidence:
            lines.append(f"依据=\n{evidence}")
        if observations:
            lines.append("已观察=\n" + "\n".join(f"- {o}" for o in observations[-8:]))
        if materials.scene_seeds:
            lines.append("抽词种子=" + "、".join(materials.scene_seeds[:8]))
        raw = self._llm.generate_json(
            system=self._SYSTEM_UNITS,
            user="\n".join(lines),
            session_id=session_id,
            director="screenwriter_units",
            turn_index=turn_index,
        )
        data = extract_json_object(raw)
        return data if isinstance(data, dict) else {}

    def _dispatch_look(self, action: str, materials: WritingMaterials) -> str:
        if action == "look_interaction":
            return materials.render_interaction_priority()
        if action == "look_memory":
            if not materials.memory_texts:
                return "（记忆池空）"
            lines = [
                f"[{i}] id={materials.memory_ids[i] if i < len(materials.memory_ids) else '—'} "
                f"{t}"
                for i, t in enumerate(materials.memory_texts[:8])
            ]
            return "记忆池：\n" + "\n".join(lines)
        if action == "look_share":
            if not materials.share_texts:
                return "（分享队列空）"
            return "分享队列：\n" + "\n".join(
                f"[{i}] {t}" for i, t in enumerate(materials.share_texts[:6])
            )
        if action == "look_seeds":
            if not materials.scene_seeds:
                return "（抽词种子空）"
            return "抽词种子=" + "、".join(materials.scene_seeds[:12])
        if action == "look_fate_panel":
            desire = (
                f"{int(materials.fate_speak_desire)}/100"
                if materials.fate_speak_desire is not None
                else "—"
            )
            return (
                f"命运骰开口欲={desire}（{materials.fate_tendency or '—'}）；"
                f"面板 mood={materials.presence_mood or '—'}；"
                f"brief={materials.presence_brief or '—'}"
            )
        if action == "look_scene":
            bits = []
            if materials.persona_brief:
                bits.append(f"人格=\n{materials.persona_brief[:400]}")
            if materials.scene_grounded:
                bits.append(f"场景=\n{materials.scene_grounded[:600]}")
            if materials.world_brief:
                bits.append(f"世界=\n{materials.world_brief[:400]}")
            return "\n".join(bits) if bits else "（无场景/人格材料）"
        return "（未知 look）"

    def _extract_outline(
        self,
        raw: dict[str, Any],
        materials: WritingMaterials,
    ) -> dict[str, Any]:
        plot_arc = raw.get("plot_arc") if isinstance(raw.get("plot_arc"), dict) else {}
        side = raw.get("side") if isinstance(raw.get("side"), dict) else {}
        if not side:
            side = {
                "mood": materials.presence_mood or "平静",
                "brief": materials.presence_brief or "在场",
                "user_identity": "同场的来访者",
                "user_activity": "在场，尚未开口",
            }
        return {
            "action": "advance",
            "plot_arc": {
                "summary": str(plot_arc.get("summary") or "").strip(),
                "evidence": str(plot_arc.get("evidence") or "").strip(),
                "units": [],
            },
            "side": side,
            "reason": str(raw.get("reason") or "agent_produce_outline").strip(),
        }

    def _extract_produce(
        self,
        raw: dict[str, Any],
        materials: WritingMaterials,
    ) -> dict[str, Any]:
        plot_arc = raw.get("plot_arc") if isinstance(raw.get("plot_arc"), dict) else {}
        units = self._parse_units(plot_arc)
        plot_flow = raw.get("plot_flow") if isinstance(raw.get("plot_flow"), dict) else {}
        side = raw.get("side") if isinstance(raw.get("side"), dict) else {}
        mem_ids = raw.get("memory_unit_ids") or []
        if not isinstance(mem_ids, list):
            mem_ids = []
        share_idx = raw.get("share_indices") or []
        if not isinstance(share_idx, list):
            share_idx = []
        if "inject_memory" in raw or mem_ids:
            plot_flow = {
                **plot_flow,
                "inject_memory": bool(raw.get("inject_memory", bool(mem_ids))),
                "memory_unit_ids": [str(x) for x in mem_ids if str(x).strip()],
            }
        if "inject_share" in raw or share_idx:
            plot_flow = {
                **plot_flow,
                "inject_share": bool(raw.get("inject_share", bool(share_idx))),
                "share_indices": [
                    int(x) for x in share_idx if str(x).lstrip("-").isdigit()
                ],
            }
        if not side:
            side = {
                "mood": materials.presence_mood or "平静",
                "brief": materials.presence_brief or "在场",
                "user_identity": "同场的来访者",
                "user_activity": "在场，尚未开口",
            }
        return {
            "action": "advance",
            "plot_arc": {
                "summary": str(plot_arc.get("summary") or "").strip(),
                "evidence": str(plot_arc.get("evidence") or "").strip(),
                "units": units,
            },
            "plot_flow": {
                "chronicle": str(plot_flow.get("chronicle") or "").strip(),
                "interaction_process": str(plot_flow.get("interaction_process") or "").strip()
                or materials.render_interaction_process(),
                "focus_now": str(plot_flow.get("focus_now") or "").strip(),
                "next_push": str(plot_flow.get("next_push") or "").strip(),
                "beat": str(plot_flow.get("beat") or "").strip(),
                "beat_kind": str(plot_flow.get("beat_kind") or "open").strip(),
                "inject_memory": bool(plot_flow.get("inject_memory")),
                "memory_unit_ids": list(plot_flow.get("memory_unit_ids") or []),
                "inject_share": bool(plot_flow.get("inject_share")),
                "share_indices": list(plot_flow.get("share_indices") or []),
            },
            "opening": "",
            "side": side,
            "reason": str(raw.get("reason") or "agent_produce_plot").strip(),
        }

    def _merge_init_jobs(
        self,
        outline: dict[str, Any],
        *,
        opening: str,
        units: list[dict[str, Any]],
        units_raw: dict[str, Any],
        materials: WritingMaterials,
    ) -> dict[str, Any]:
        arc = outline.get("plot_arc") if isinstance(outline.get("plot_arc"), dict) else {}
        summary = str(arc.get("summary") or "").strip()
        first = str(units[0].get("intent") or "").strip() if units else "继续手头未完成的活计"
        second = (
            str(units[1].get("intent") or "").strip()
            if len(units) > 1
            else first
        )
        hint = next((s for s in materials.scene_seeds if is_usable_scene_seed(s)), "手头物件")
        mem_ids = units_raw.get("memory_unit_ids") or []
        if not isinstance(mem_ids, list):
            mem_ids = []
        share_idx = units_raw.get("share_indices") or []
        if not isinstance(share_idx, list):
            share_idx = []
        return {
            "action": "advance",
            "plot_arc": {
                "summary": summary,
                "evidence": str(arc.get("evidence") or "").strip(),
                "units": units,
            },
            "plot_flow": {
                "chronicle": "灯下，角色按大纲开场，手上有未完成的活计。",
                "interaction_process": materials.render_interaction_process(),
                "focus_now": first or f"整理眼前的{hint}",
                "next_push": second or f"把{hint}再确认一遍",
                "beat": f"角色在场，手边是{hint}。",
                "beat_kind": "open",
                "inject_memory": bool(units_raw.get("inject_memory", bool(mem_ids))),
                "memory_unit_ids": [str(x) for x in mem_ids if str(x).strip()],
                "inject_share": bool(units_raw.get("inject_share", bool(share_idx))),
                "share_indices": [
                    int(x) for x in share_idx if str(x).lstrip("-").isdigit()
                ],
            },
            "opening": opening,
            "side": outline.get("side")
            if isinstance(outline.get("side"), dict)
            else {
                "mood": materials.presence_mood or "平静",
                "brief": materials.presence_brief or "在场",
                "user_identity": "同场的来访者",
                "user_activity": "在场，尚未开口",
            },
            "reason": "agent_init_three_jobs",
        }

    @staticmethod
    def _parse_units(plot_arc: dict[str, Any]) -> list[dict[str, Any]]:
        units_raw = plot_arc.get("units") or []
        units: list[dict[str, Any]] = []
        if not isinstance(units_raw, list):
            return units
        for item in units_raw:
            if isinstance(item, str) and item.strip():
                units.append({"intent": item.strip(), "span_polls": 2})
            elif isinstance(item, dict) and str(item.get("intent") or "").strip():
                units.append(
                    {
                        "intent": str(item.get("intent") or "").strip(),
                        "evidence": str(item.get("evidence") or "").strip(),
                        "span_polls": int(item.get("span_polls") or 2),
                    }
                )
        return units

    def _heuristic_opening(self, materials: WritingMaterials, summary: str) -> str:
        hint = ""
        for seed in materials.scene_seeds:
            if is_usable_scene_seed(seed):
                hint = seed
                break
        if hint:
            return f"灯还亮着。你看见她低着头，手指停在{hint}附近，还没抬头。"
        if summary:
            clip = summary.rstrip("。")[:24]
            return f"灯还亮着。你看见她正按「{clip}」往下做。"
        return "灯还亮着。你看见她低着头，手上还停着未做完的活计。"

    def _heuristic(
        self,
        materials: WritingMaterials,
        *,
        reason: str,
    ) -> ScreenwriterAgentResult:
        seeds = [s for s in materials.scene_seeds[:8] if is_usable_scene_seed(s)] or ["手头物件"]
        mem = list(materials.memory_texts[:3])
        share = list(materials.share_texts[:1])
        units: list[dict[str, Any]] = []
        for i in range(self._target_units):
            seed = seeds[i % len(seeds)]
            if i < 3 and mem:
                intent = f"对照记忆「{mem[i % len(mem)][:24]}」，整理眼前的{seed}"
            elif share and i == self._target_units - 2:
                intent = f"斟酌是否提起「{share[0][:28]}」"
            else:
                intent = f"围绕{seed}再推进一小步观察或整理"
            units.append({"intent": intent, "evidence": seed, "span_polls": 2})
        hint = seeds[0]
        payload = {
            "action": "advance",
            "plot_arc": {
                "summary": (
                    f"角色停在{hint}旁，手头有未完成的活计；"
                    f"先把眼前的{hint}理清，再对照可取用的材料往下观察，"
                    f"中间若有来访者，会先把手头告一段落再抬眼，最后落到可开口或继续收拾的收束。"
                ),
                "evidence": "；".join(mem[:2]) if mem else hint,
                "units": units,
            },
            "plot_flow": {
                "chronicle": f"灯下，角色停在{hint}旁，手上有未完成的活计。",
                "interaction_process": materials.render_interaction_process(),
                "focus_now": f"角色正整理眼前的{hint}",
                "next_push": f"把{hint}再确认一遍",
                "beat": f"角色在场，手边是{hint}。",
                "beat_kind": "open",
                "inject_memory": bool(materials.memory_ids),
                "memory_unit_ids": list(materials.memory_ids[:2]),
                "inject_share": bool(materials.share_texts),
                "share_indices": [0] if materials.share_texts else [],
            },
            "opening": self._heuristic_opening(materials, ""),
            "side": {
                "mood": materials.presence_mood or "平静",
                "brief": materials.presence_brief or f"在整理{hint}",
                "user_identity": "同场的来访者",
                "user_activity": "在场，尚未开口",
            },
            "reason": reason,
        }
        return ScreenwriterAgentResult(
            payload=payload,
            reason=reason,
            used_fallback=True,
            steps=(),
            lookups=(),
        )

    @staticmethod
    def _merge_payload(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        out = dict(fallback)
        out.update({k: v for k, v in primary.items() if v})
        arc_p = primary.get("plot_arc") if isinstance(primary.get("plot_arc"), dict) else {}
        arc_f = fallback.get("plot_arc") if isinstance(fallback.get("plot_arc"), dict) else {}
        units_p = list(arc_p.get("units") or [])
        units_f = list(arc_f.get("units") or [])
        units = units_p if len(units_p) >= len(units_f) else units_f
        out["plot_arc"] = {
            "summary": str(arc_p.get("summary") or arc_f.get("summary") or "").strip(),
            "evidence": str(arc_p.get("evidence") or arc_f.get("evidence") or "").strip(),
            "units": units,
        }
        return out
