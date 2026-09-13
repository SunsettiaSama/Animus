from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

_USER_PREFIXES = ("用户：", "用户:", "U:", "u:", "对方：", "对方:")
_AGENT_MARKERS = ("｜角色：", "|角色：", "角色：", "A:", "a:")

# 用户存在软约束：编剧不导演用户，但故事线要合理容纳交互（含「暂时不回」的停顿）。
# 各书写席位（大纲/unit/场记/演出表）共用。
USER_PRESENCE_RULE = (
    "用户是屏幕外的真实一方：不描写用户的动作、行踪与心情，不替用户说话；"
    "用户那边发生了什么只以交互记录为准，没发生的不要编。\n"
    "但用户与角色的往来要被故事线合理容纳：用户随时可能发来消息；"
    "角色可能立刻回、可能拖一拖、也可能正烦闷先搁着不回——"
    "这些都是正常的一拍，不是剧情中断。\n"
    "安排剧情时给交互留出余地：任何一步都容得下「消息来了但角色暂时没接」，"
    "后续步骤不因用户暂时沉默而卡死或倒退。\n"
)


def _user_ingress_lines(
    last_user_text: str,
    recent_turns: tuple[str, ...] | list[str],
) -> list[str]:
    """只取用户侧入站，丢掉角色台词。"""
    out: list[str] = []
    for raw in recent_turns:
        line = str(raw or "").strip()
        if not line:
            continue
        for marker in _AGENT_MARKERS:
            if marker in line:
                line = line.split(marker, 1)[0].strip()
                break
        for prefix in _USER_PREFIXES:
            if line.startswith(prefix):
                line = line[len(prefix):].strip()
                break
        if line:
            out.append(line[:240])
    last = str(last_user_text or "").strip()
    if last and (not out or out[-1] != last[:240]):
        out.append(last[:240])
    return out


@dataclass
class WritingMaterials:
    """编剧书写材料：外部注入统一抽象，供编剧展开为 unit / 大纲 / 场记。

    高优先级：与用户的交互记录（含时间元数据），直接注入编剧提示。
    其余为可选粘土：命运骰、临场面板、场景/世界观、记忆池、分享队列、抽词种子。
    """

    # 高优先级：交互轨迹
    dialogue_history: str = ""
    recent_turns: tuple[str, ...] = ()
    silence_log: tuple[str, ...] = ()
    last_user_text: str = ""
    last_user_speak_at: float = 0.0
    last_agent_speak_at: float = 0.0

    # 命运骰 / 临场面板
    fate_speak_desire: int | None = None
    fate_tendency: str = ""
    presence_mood: str = ""
    presence_brief: str = ""
    persona_brief: str = ""

    # 场景 / 世界观
    scene_grounded: str = ""
    world_brief: str = ""

    # 记忆池 / 分享队列
    memory_ids: tuple[str, ...] = ()
    memory_texts: tuple[str, ...] = ()
    share_texts: tuple[str, ...] = ()
    director_memory_texts: tuple[str, ...] = ()

    # 1 小时内即将到点的手账地标（角色自己预约的叙事时刻）
    landmark_briefs: tuple[str, ...] = ()

    def render_landmarks(self) -> str:
        if not self.landmark_briefs:
            return ""
        return "即将到点的手账地标：\n" + "\n".join(
            f"- {t}" for t in self.landmark_briefs[:4]
        )

    # 抽词器（约 k=10）
    scene_seeds: tuple[str, ...] = ()

    # 角色回馈编剧
    character_feedback: tuple[str, ...] = ()

    # 原始 compose meta 残留（调试用，不进主提示）
    raw_meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """兼容旧 materials dict 键名，便于现有调度逻辑复用。"""
        out = dict(self.raw_meta) if isinstance(self.raw_meta, dict) else {}
        out.update(
            {
                "dynamic_memory_ids": list(self.memory_ids),
                "dynamic_memory_texts": list(self.memory_texts),
                "dynamic_share_texts": list(self.share_texts),
                "compose_manager_director_memory_texts": list(self.director_memory_texts),
                "persona_brief": self.persona_brief,
                "scene_seeds": list(self.scene_seeds),
                "scene_grounded": self.scene_grounded,
                "world_brief": self.world_brief,
                "fate_speak_desire": self.fate_speak_desire,
                "fate_tendency": self.fate_tendency,
                "presence_mood": self.presence_mood,
                "presence_brief": self.presence_brief,
                "dialogue_history": self.dialogue_history,
                "recent_turns": list(self.recent_turns),
                "silence_log": list(self.silence_log),
                "last_user_text": self.last_user_text,
                "character_feedback_to_screenwriter": list(self.character_feedback),
                "writing_materials": True,
            }
        )
        return out

    def render_interaction_process(self, *, now: float | None = None) -> str:
        """客观写清：用户交互如何发生，以及对角色后续的影响。不写角色台词。"""
        current = time.time() if now is None else float(now)
        user_lines = _user_ingress_lines(
            self.last_user_text,
            self.recent_turns,
        )
        if not user_lines and not self.silence_log:
            return ""
        parts: list[str] = []
        if user_lines:
            latest = user_lines[-1]
            parts.append(f"对方从屏幕外发来：「{latest}」")
            if len(user_lines) > 1:
                earlier = "；".join(f"「{line}」" for line in user_lines[-4:-1])
                parts.append(f"此前还来过：{earlier}。")
        else:
            parts.append("对方尚未从屏幕外开口。")
        if self.last_user_speak_at > 0:
            parts.append(
                f"这句落在距上次对方开口 {current - float(self.last_user_speak_at):.1f} 秒的当口。"
            )
        if self.silence_log:
            parts.append("此前静默：" + " / ".join(self.silence_log[-3:]))
        parts.append("后续场记须写清这句把角色注意点与手头活计带向何处。")
        return "\n".join(parts).strip()

    def render_interaction_priority(self, *, now: float | None = None) -> str:
        """交互记录——编剧提示最高优先级块：如何发生、对角色的影响。"""
        current = time.time() if now is None else float(now)
        lines = ["【交互记录｜高优先级｜如何发生 / 对角色的影响】"]
        process = self.render_interaction_process(now=current)
        if process:
            lines.append(process)
        else:
            lines.append("（尚无用户交互）")
        return "\n".join(lines)

    def render_clay_blocks(self) -> str:
        """其余书写材料：编剧可自由展开为 unit / 场面抓手。"""
        blocks: list[str] = ["【书写材料｜可选粘土｜自由取用】"]
        if self.fate_speak_desire is not None or self.fate_tendency.strip():
            desire = (
                f"{int(self.fate_speak_desire)}/100"
                if self.fate_speak_desire is not None
                else "—"
            )
            blocks.append(
                f"命运骰：开口欲={desire}"
                + (f"（{self.fate_tendency.strip()}）" if self.fate_tendency.strip() else "")
            )
        panel_bits = [
            x
            for x in (
                f"mood={self.presence_mood.strip()}" if self.presence_mood.strip() else "",
                f"brief={self.presence_brief.strip()}" if self.presence_brief.strip() else "",
            )
            if x
        ]
        if panel_bits:
            blocks.append("角色面板：" + "；".join(panel_bits))
        if self.persona_brief.strip():
            blocks.append(f"人格摘要=\n{self.persona_brief.strip()[:400]}")
        if self.scene_grounded.strip():
            blocks.append(f"场景锚定=\n{self.scene_grounded.strip()[:800]}")
        if self.world_brief.strip():
            blocks.append(f"世界观请求=\n{self.world_brief.strip()[:600]}")
        if self.memory_texts:
            blocks.append(
                "记忆池=\n" + "\n".join(f"- {t[:160]}" for t in self.memory_texts[:6])
            )
        if self.share_texts:
            blocks.append(
                "分享队列=\n" + "\n".join(f"- {t[:160]}" for t in self.share_texts[:4])
            )
        if self.scene_seeds:
            blocks.append("抽词种子（约十词）=" + "、".join(self.scene_seeds[:10]))
        if self.character_feedback:
            blocks.append(
                "角色反馈=\n"
                + "\n".join(f"- {t[:160]}" for t in self.character_feedback[-6:])
            )
        if len(blocks) == 1:
            blocks.append("（本拍无额外粘土材料）")
        return "\n".join(blocks)

    def render_for_screenwriter(self, *, now: float | None = None) -> str:
        return (
            self.render_interaction_priority(now=now)
            + "\n\n"
            + self.render_clay_blocks()
        )


def build_writing_materials(
    *,
    compose_meta: dict[str, Any] | None = None,
    fate_speak_desire: int | None = None,
    fate_tendency: str = "",
    presence_mood: str = "",
    presence_brief: str = "",
    grounded: str = "",
    world_brief: str = "",
    dialogue_history: str = "",
    recent_turns: tuple[str, ...] | list[str] | None = None,
    silence_log: tuple[str, ...] | list[str] | None = None,
    last_user_text: str = "",
    last_user_speak_at: float = 0.0,
    last_agent_speak_at: float = 0.0,
    scene_seeds: tuple[str, ...] | list[str] | None = None,
    character_feedback: tuple[str, ...] | list[str] | None = None,
) -> WritingMaterials:
    meta = dict(compose_meta) if isinstance(compose_meta, dict) else {}
    mem_ids = tuple(
        str(x).strip() for x in (meta.get("dynamic_memory_ids") or []) if str(x).strip()
    )
    mem_texts = tuple(
        str(x).strip() for x in (meta.get("dynamic_memory_texts") or []) if str(x).strip()
    )
    share_texts = tuple(
        str(x).strip() for x in (meta.get("dynamic_share_texts") or []) if str(x).strip()
    )
    dir_texts = tuple(
        str(x).strip()
        for x in (meta.get("compose_manager_director_memory_texts") or [])
        if str(x).strip()
    )
    persona = str(meta.get("persona_brief") or meta.get("persona") or "").strip()
    seeds = scene_seeds
    if seeds is None:
        seeds = meta.get("scene_seeds") or ()
    fb = character_feedback
    if fb is None:
        raw_fb = meta.get("character_feedback_to_screenwriter") or meta.get(
            "screenwriter_character_notes"
        )
        notes: list[str] = []
        if isinstance(raw_fb, list):
            for item in raw_fb:
                if isinstance(item, dict):
                    text = str(item.get("text") or "").strip()
                else:
                    text = str(item or "").strip()
                if text:
                    notes.append(text)
        fb = notes
    return WritingMaterials(
        dialogue_history=str(dialogue_history or meta.get("dialogue_history") or "").strip(),
        recent_turns=tuple(str(x) for x in (recent_turns or ()) if str(x).strip()),
        silence_log=tuple(str(x) for x in (silence_log or ()) if str(x).strip()),
        last_user_text=str(last_user_text or meta.get("last_user_text") or "").strip(),
        last_user_speak_at=float(last_user_speak_at or 0.0),
        last_agent_speak_at=float(last_agent_speak_at or 0.0),
        fate_speak_desire=fate_speak_desire
        if fate_speak_desire is not None
        else (
            int(meta["fate_speak_desire"])
            if str(meta.get("fate_speak_desire") or "").strip().lstrip("-").isdigit()
            else None
        ),
        fate_tendency=str(fate_tendency or meta.get("fate_tendency") or "").strip(),
        presence_mood=str(presence_mood or meta.get("presence_mood") or "").strip(),
        presence_brief=str(presence_brief or meta.get("presence_brief") or "").strip(),
        persona_brief=persona,
        scene_grounded=str(grounded or meta.get("scene_grounded") or "").strip(),
        world_brief=str(world_brief or meta.get("world_brief") or "").strip(),
        memory_ids=mem_ids,
        memory_texts=mem_texts,
        share_texts=share_texts,
        director_memory_texts=dir_texts,
        scene_seeds=tuple(str(x).strip() for x in (seeds or ()) if str(x).strip())[:10],
        landmark_briefs=tuple(
            str(x).strip() for x in (meta.get("landmark_briefs") or ()) if str(x).strip()
        )[:4],
        character_feedback=tuple(str(x) for x in (fb or ()) if str(x).strip()),
        raw_meta=meta,
    )
