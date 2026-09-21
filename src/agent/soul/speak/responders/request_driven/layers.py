from __future__ import annotations

import os
from dataclasses import dataclass

from agent.soul.speak.responders.request_driven.composer.projectors.dynamic_layer import (
    DynamicLayerMaterials,
    DynamicLayerSchedule,
)
from agent.soul.speak.responders.request_driven.composer.projectors.role_view import (
    RoleContextView,
)
from agent.soul.speak.responders.request_driven.protocol.scrub import scrub_compose_markup

# 策略与材料分离：指令性文本已全部上移至 blocks/system/role.py 三段式 role。
# 本文件 render_system_extra() 只产出材料与事实标注；policy-lint 会对
# 指令模式（<speak>、"请勿" 等）在动态层出现时告警。

# 评测消融开关（evals/speak_humaneness）：动态层卡片族过滤/改写。
# ""             = 不过滤（生产行为，但仍受 REACT_SPEAK_RHYTHM_CARDS 影响）
# "writer"       = 只保留剧情卡片（blank 导演/节奏族）
# "director"     = 只保留导演/节奏卡片（blank 剧情族 + pass_info）
# "dynsched"     = 节奏卡片出清 + 阈值策略接管注入（已被证伪的便宜版，留作对照）
# "dynsched_llm" = 节奏卡出清 + 导演 LLM 判定注入（v1：只见对话近况）
# "softplot"     = 节奏卡出清（软约束措辞已是生产默认）
# "charsilence"  = 角色自主臂：沉默权（只回「……」）+ 自预约下一拍（存入上下文回显）
# "combo"        = 软约束剧情 + 导演 LLM 调度（v1 判定）组合
# "combo_v2"     = 软约束剧情 + 新导演判定（v2：喂入剧情材料对齐 + 中性权衡 prompt）
# 按调用即时读取，进程内生效。
CARD_FAMILY_FILTER_ENV = "SPEAK_EVAL_CARD_FAMILY"

# 生产开关：REACT_SPEAK_RHYTHM_CARDS=off 时动态层不出导演/节奏卡
# （rd_combo 优胜形态；与评测消融臂同一份出清字段表）。
RHYTHM_CARDS_ENV = "REACT_SPEAK_RHYTHM_CARDS"


def rhythm_cards_enabled() -> bool:
    return os.environ.get(RHYTHM_CARDS_ENV, "").strip().lower() != "off"

_RHYTHM_BLANK_MODES = (
    "writer",
    "dynsched",
    "dynsched_llm",
    "softplot",
    "combo",
    "combo_v2",
)
_JUDGE_HOOK_MODES = ("dynsched_llm", "combo", "combo_v2")

_SOFT_PLOT_OUTLINE_HEADER = (
    "参考剧情（软约束——她正处于此剧情中，供构思对用户的回复参考；"
    "对方当前的发言优先于剧情推进）：\n"
)
_SOFT_PLOT_FLOW_HEADER = "此刻情景（软约束，参考，以对方的话为先）：\n"
_USER_POSITION_NOTE = (
    "对方在剧情中的位置：对方是此刻正与你实时对话的人。"
    "剧情没有为对方的发言安排位置时，以对方的发言为准，剧情退为背景参考。"
)
_CHAR_AUTONOMY_NOTE = (
    "本拍自主权（导演离席，由你自理）：\n"
    "- 若确实无话可说，可以只回「……」表示沉默，不必硬找话说；\n"
    "- 你可以为自己预约下一次想开口聊的事：单独一行以「预约：」开头写下，"
    "下一拍会回显给你作提醒。"
)


def _card_family_filter() -> str:
    return os.environ.get(CARD_FAMILY_FILTER_ENV, "").strip().lower()


# ── 评测专用注入判定钩子（dynsched_llm）───────────────────────────────────────
# 签名: (session_id, user_text, frame_text, memory_texts, share_texts)
#       -> (memory_keep_indices, share_keep_indices)
# 由 evals.speak_humaneness 在装配时注入；生产恒为 None（不判定、全保留）。
_EVAL_UNIT_JUDGE = None


def set_eval_unit_judge(judge) -> None:
    global _EVAL_UNIT_JUDGE
    _EVAL_UNIT_JUDGE = judge


# ── 评测专用角色自预约存档（charsilence）──────────────────────────────────────
# key=session_id，value=角色写下的预约行；由评测端口写入、render 回显，生产不读。
EVAL_CHAR_BOOKINGS: dict[str, list[str]] = {}


@dataclass(frozen=True)
class RoleStaticLayer:
    """静态层已并入 system role（见 blocks/system/role.py），保留壳以兼容装配。"""

    protocol: str = ""


@dataclass(frozen=True)
class RoleDynamicLayer:
    """动态层：只包含导演已调度选中的可注入内容。"""

    memory_texts: tuple[str, ...] = ()
    share_texts: tuple[str, ...] = ()
    pass_info_texts: tuple[str, ...] = ()
    presence_mood: str = ""
    presence_brief: str = ""
    presence_speak_desire: int | None = None
    presence_fate_tendency: str = ""
    user_identity: str = ""
    user_activity: str = ""
    interaction_channel: str = ""
    plot_outline_text: str = ""
    plot_flow_text: str = ""
    scene_event: str = ""
    silence_log_text: str = ""
    director_focus: str = ""
    director_intent: str = ""
    director_direction: str = ""
    director_exit: str = ""
    director_detail: str = ""
    director_inner: str = ""
    director_transition: str = ""
    director_stance: str = ""
    interaction_record_text: str = ""
    schedule_reason: str = ""
    help_observations: tuple[str, ...] = ()

    def presence_card_text(self) -> str:
        lines: list[str] = []
        if self.presence_mood.strip():
            lines.append(f"心情：{self.presence_mood.strip()}")
        if self.presence_speak_desire is not None:
            desire = max(0, min(100, int(self.presence_speak_desire)))
            band = self.presence_fate_tendency.strip() or "—"
            lines.append(f"开口欲：{desire}/100（{band}）")
        if self.presence_brief.strip():
            lines.append(f"简述：{self.presence_brief.strip()}")
        return "\n".join(lines)

    def user_stage_text(self) -> str:
        lines: list[str] = []
        if self.user_identity.strip():
            lines.append(f"身份：{self.user_identity.strip()}")
        if self.user_activity.strip():
            lines.append(f"正在做：{self.user_activity.strip()}")
        return "\n".join(lines)


@dataclass(frozen=True)
class RolePromptLayers:
    static: RoleStaticLayer
    dynamic: RoleDynamicLayer
    dialogue_frame: str = ""
    user_text: str = ""
    session_id: str = ""

    def render_system_extra(self) -> str:
        """纯材料区：只含事实标注与材料正文，不含任何指令性文本。"""
        parts: list[str] = []
        # 角色与用户的往来记录优先放入上下文
        if self.user_text.strip():
            parts.append(
                "对方刚发来的消息：\n" + self.user_text.strip()
            )
        if self.dynamic.interaction_record_text.strip():
            parts.append(self.dynamic.interaction_record_text.strip())
        elif self.dialogue_frame.strip():
            parts.append(self.dialogue_frame.strip())
        dyn_blocks: list[str] = []
        # 剧情卡以软约束呈现（拟人度评测 R3/R5 结论：硬性"客观材料"框架会让
        # 角色越过对方发言推进剧情；软约束 + 显式用户位置显著修复场景失败）。
        if self.dynamic.plot_outline_text.strip():
            dyn_blocks.append(
                _SOFT_PLOT_OUTLINE_HEADER + self.dynamic.plot_outline_text.strip()
            )
        if self.dynamic.plot_flow_text.strip():
            dyn_blocks.append(
                _SOFT_PLOT_FLOW_HEADER + self.dynamic.plot_flow_text.strip()
            )
        if (
            self.dynamic.plot_outline_text.strip()
            or self.dynamic.plot_flow_text.strip()
        ):
            dyn_blocks.append(_USER_POSITION_NOTE)
        stage = self.dynamic.user_stage_text()
        if stage:
            dyn_blocks.append("对方当前舞台信息：\n" + stage)
        # 如果没有情景材料，才回落到临场事件
        if (
            not self.dynamic.plot_flow_text.strip()
            and self.dynamic.scene_event.strip()
        ):
            dyn_blocks.append(
                "临场事件纪要：\n" + self.dynamic.scene_event.strip()
            )
        presence = self.dynamic.presence_card_text()
        if presence:
            dyn_blocks.append("你的临场状态：\n" + presence)
        note_lines: list[str] = []
        detail = self.dynamic.director_detail.strip() or self.dynamic.director_focus.strip()
        inner = self.dynamic.director_inner.strip() or self.dynamic.director_intent.strip()
        transition = (
            self.dynamic.director_transition.strip()
            or self.dynamic.director_direction.strip()
        )
        stance = self.dynamic.director_stance.strip() or self.dynamic.director_exit.strip()
        if detail:
            note_lines.append(f"手头动作：{detail}")
        if inner:
            note_lines.append(f"内心状态：{inner}")
        if transition:
            note_lines.append(f"过渡方式：{transition}")
        if stance:
            note_lines.append(f"姿态：{stance}")
        if note_lines:
            # 「你」在笔记中指角色自己——此标注是人称消歧，不是指令；
            # 对应的"勿带入旁观口吻"规则在 system role 第三段。
            dyn_blocks.append(
                "本拍处境笔记（此处「你」指角色自己）：\n"
                + "\n".join(note_lines)
            )
        if self.dynamic.memory_texts:
            dyn_blocks.append(
                "本轮一次性记忆卡片：\n"
                + "\n".join(f"- {t}" for t in self.dynamic.memory_texts)
            )
        if self.dynamic.share_texts:
            dyn_blocks.append(
                "本轮一次性分享卡片：\n"
                + "\n".join(f"- {t}" for t in self.dynamic.share_texts)
            )
        if self.dynamic.pass_info_texts:
            dyn_blocks.append(
                "编剧经剧情流传递的信息：\n"
                + "\n".join(f"- {t}" for t in self.dynamic.pass_info_texts)
            )
        if self.dynamic.help_observations:
            dyn_blocks.append(
                "后台回传，作处境参考：\n"
                + "\n".join(f"- {t}" for t in self.dynamic.help_observations)
            )
        if _card_family_filter() == "charsilence":
            parts.append(_CHAR_AUTONOMY_NOTE)
            bookings = EVAL_CHAR_BOOKINGS.get(self.session_id) or []
            if bookings:
                parts.append(
                    "你自己预约的下一拍：\n"
                    + "\n".join(f"- {t}" for t in bookings[-2:])
                )
        if dyn_blocks:
            parts.append("\n\n".join(dyn_blocks))
        return "\n\n".join(p for p in parts if p.strip())


def build_dialogue_frame(view: RoleContextView) -> str:
    chunks: list[str] = []
    if view.history_distilled:
        distilled = [
            scrub_compose_markup(line)
            for line in view.history_distilled[-6:]
            if scrub_compose_markup(line)
        ]
        if distilled:
            chunks.append("对话轨迹（已压缩）：\n" + "\n".join(distilled))
    if view.working_turns:
        lines: list[str] = []
        for user, agent in view.working_turns[-4:]:
            u = scrub_compose_markup(user)
            a = scrub_compose_markup(agent)
            if not u and not a:
                continue
            lines.append(f"用户：{u}\n你：{a}")
        if lines:
            chunks.append("对话轨迹（未压缩）：\n" + "\n".join(lines))
    return "\n\n".join(chunks)


def assemble_role_layers(
    view: RoleContextView,
    materials: DynamicLayerMaterials,
    schedule: DynamicLayerSchedule,
    *,
    user_text: str,
    behavior_guide: str = "",
    script_hint: str = "",
    help_observations: tuple[str, ...] = (),
    presence_mood: str = "",
    presence_brief: str = "",
    presence_speak_desire: int | None = None,
    presence_fate_tendency: str = "",
    user_identity: str = "",
    user_activity: str = "",
    interaction_channel: str = "",
    plot_outline_text: str = "",
    plot_flow_text: str = "",
    scene_event: str = "",
    silence_log_text: str = "",
    director_focus: str = "",
    director_intent: str = "",
    director_direction: str = "",
    director_exit: str = "",
    director_detail: str = "",
    director_inner: str = "",
    director_transition: str = "",
    director_stance: str = "",
    interaction_record_text: str = "",
) -> RolePromptLayers:
    # 评测消融：卡片族过滤/改写（见 CARD_FAMILY_FILTER_ENV）。
    family = _card_family_filter()

    # 导演策略接管注入（dynsched）：先于节奏族出清计算，用原始 presence 信号做判定。
    selected_memory = schedule.selected_memory_texts(materials)
    selected_share = schedule.selected_share_texts(materials)
    selected_pass_info = (
        () if family == "director" else schedule.selected_pass_info_texts(materials)
    )
    if family == "dynsched":
        # 评测结论：记忆可精准共情但混有干扰记忆 → 截断，只留最相关的前两条
        selected_memory = selected_memory[:2]
        # 是否分享交给导演态判定：开口欲不足时不注入待分享事项
        desire = presence_speak_desire if presence_speak_desire is not None else -1
        if desire < 60:
            selected_share = ()
    elif family in _JUDGE_HOOK_MODES and _EVAL_UNIT_JUDGE is not None and (
        selected_memory or selected_share
    ):
        # 导演 LLM 判定注入。plot_context 为编剧线程产出的剧情材料，
        # 同步喂给导演做剧情对齐（模拟导演/编剧两线程交互）；v1 判定器忽略它。
        frame_text = build_dialogue_frame(view)
        plot_context = "\n".join(
            part
            for part in (plot_outline_text.strip(), plot_flow_text.strip())
            if part
        )
        keep_mem, keep_share = _EVAL_UNIT_JUDGE(
            view.session_id,
            user_text,
            frame_text,
            selected_memory,
            selected_share,
            plot_context,
        )
        selected_memory = tuple(
            selected_memory[int(i)]
            for i in keep_mem
            if 0 <= int(i) < len(selected_memory)
        )
        selected_share = tuple(
            selected_share[int(i)]
            for i in keep_share
            if 0 <= int(i) < len(selected_share)
        )

    # 节奏卡片出清：评测消融臂（_RHYTHM_BLANK_MODES）或生产开关
    # REACT_SPEAK_RHYTHM_CARDS=off（拟人度评测 R2~R5 结论：导演/节奏卡入
    # 提示词会把回复撑满、盲测被识破；rd_combo 优胜形态即节奏卡出清）。
    if family in _RHYTHM_BLANK_MODES or not rhythm_cards_enabled():
        director_focus = ""
        director_intent = ""
        director_direction = ""
        director_exit = ""
        director_detail = ""
        director_inner = ""
        director_transition = ""
        director_stance = ""
        presence_mood = ""
        presence_brief = ""
        presence_speak_desire = None
        presence_fate_tendency = ""
        user_identity = ""
        user_activity = ""
    if family == "director":  # 只保留导演/节奏卡片：blank 剧情族
        plot_outline_text = ""
        plot_flow_text = ""
        scene_event = ""

    dynamic = RoleDynamicLayer(
        memory_texts=selected_memory,
        share_texts=selected_share,
        pass_info_texts=selected_pass_info,
        presence_mood=presence_mood.strip(),
        presence_brief=presence_brief.strip(),
        presence_speak_desire=presence_speak_desire,
        presence_fate_tendency=presence_fate_tendency.strip(),
        user_identity=user_identity.strip(),
        user_activity=user_activity.strip(),
        interaction_channel=interaction_channel.strip(),
        plot_outline_text=plot_outline_text.strip(),
        plot_flow_text=plot_flow_text.strip(),
        scene_event=scene_event.strip(),
        silence_log_text="",
        director_focus=director_focus.strip(),
        director_intent=director_intent.strip(),
        director_direction=director_direction.strip(),
        director_exit=director_exit.strip(),
        director_detail=(director_detail or director_focus).strip(),
        director_inner=(director_inner or director_intent).strip(),
        director_transition=(director_transition or director_direction).strip(),
        director_stance=(director_stance or director_exit).strip(),
        interaction_record_text=interaction_record_text.strip(),
        schedule_reason=schedule.reason,
        help_observations=tuple(t for t in help_observations if str(t).strip()),
    )
    return RolePromptLayers(
        static=RoleStaticLayer(),
        dynamic=dynamic,
        dialogue_frame=build_dialogue_frame(view),
        user_text=user_text.strip(),
        session_id=getattr(view, "session_id", ""),
    )