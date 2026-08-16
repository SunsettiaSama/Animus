from __future__ import annotations

from dataclasses import dataclass

from agent.soul.speak.responders.request_driven.composer.projectors.dynamic_layer import (
    DynamicLayerMaterials,
    DynamicLayerSchedule,
)
from agent.soul.speak.responders.request_driven.composer.projectors.role_view import (
    RoleContextView,
)
from agent.soul.speak.responders.request_driven.protocol.scrub import scrub_compose_markup

# 交付协议：对外只走文字消息，索引由解析侧按出现顺序生成。
_ROLE_PROTOCOL_HINT = (
    "回复格式：这个端口是你对外发消息的渠道，对方是通过文字与你通信的人。"
    "所有可见表达写在 <speak> 标签里，不用写动作标签，也不用写 body。"
    "标签名按原样使用。格式如下：\n"
    "<speak>一条短消息</speak>\n"
    "如果一段话内容比较多，可以分成多条来发，不用挤进一条里。"
    "手头在做什么由导演材料提供，不用在消息里重复写动作。"
    "也可以整段留空，表示沉默。"
)

_ROLE_SOFT_AGENCY_HINT = (
    "你是角色本人，用这个端口与对方远程文字往来。"
    "代入此刻：对方发来文字时，按你会怎么回这条消息来写。"
    "不演独角戏，不把整段探索讲完，也不旁白解说自己。"
    "编剧材料提供处境参考；导演用「你」写的本拍动作、感受、过渡、姿态，是给你自己看的，不是替你写消息。"
    "对方刚发来消息时，认真回、先丢一句、或先不回应，都行。"
    "对方还没回话时，可以拆成几条来发，不用挤进一条里。发完之后停住等对方回应。"
    "人称：「你」指对方，「我」指你自己，「他/她」只指 NPC。"
    "导演材料里的「你」是对你的提示，不要把那种旁观口吻写进消息。"
)


@dataclass(frozen=True)
class RoleStaticLayer:
    """静态层：角色只产出可见的 speak 消息，人格壳由 base_system 提供。"""

    protocol: str = _ROLE_PROTOCOL_HINT


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

    def render_system_extra(self) -> str:
        parts: list[str] = [
            self.static.protocol.strip(),
        ]
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
        if self.dynamic.interaction_channel.strip():
            dyn_blocks.append(self.dynamic.interaction_channel.strip())
        if self.dynamic.plot_outline_text.strip():
            dyn_blocks.append(
                "本场故事线（客观材料）：\n"
                + self.dynamic.plot_outline_text.strip()
            )
        if self.dynamic.plot_flow_text.strip():
            dyn_blocks.append(
                "此刻情景（客观材料，你正在做什么）：\n"
                + self.dynamic.plot_flow_text.strip()
            )
        stage = self.dynamic.user_stage_text()
        if stage:
            dyn_blocks.append("对方当前舞台信息（附带参考）：\n" + stage)
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
            dyn_blocks.append("你的临场状态（附带参考）：\n" + presence)
        instruction_lines: list[str] = []
        detail = self.dynamic.director_detail.strip() or self.dynamic.director_focus.strip()
        inner = self.dynamic.director_inner.strip() or self.dynamic.director_intent.strip()
        transition = (
            self.dynamic.director_transition.strip()
            or self.dynamic.director_direction.strip()
        )
        stance = self.dynamic.director_stance.strip() or self.dynamic.director_exit.strip()
        if detail:
            instruction_lines.append(f"手头动作：{detail}")
        if inner:
            instruction_lines.append(f"内心状态：{inner}")
        if transition:
            instruction_lines.append(f"过渡方式：{transition}")
        if stance:
            instruction_lines.append(f"姿态：{stance}")
        if instruction_lines:
            dyn_blocks.append(
                "导演用「你」给出的本拍扩充如下。只写 <speak> 短消息，不用写动作：\n"
                + "\n".join(instruction_lines)
            )
        if (
            self.dynamic.plot_flow_text.strip()
            or self.dynamic.plot_outline_text.strip()
            or stage
            or self.dynamic.scene_event.strip()
            or self.dialogue_frame.strip()
            or self.dynamic.interaction_record_text.strip()
            or self.user_text.strip()
        ):
            dyn_blocks.append(_ROLE_SOFT_AGENCY_HINT)
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
        if dyn_blocks:
            header = (
                "下面是本轮动态材料。"
                "编剧维护完整故事线和此刻情景，记忆和分享按剧情流调度写入。"
                "舞台与临场状态作为附带参考。"
                "记忆与分享以卡片形式压入，本轮用完即消费。"
                "以本层列出的材料为准。"
            )
            parts.append(header + "\n\n" + "\n\n".join(dyn_blocks))
        else:
            parts.append(
                "本轮没有额外的故事线、情景或记忆分享注入。"
                "如果有临场状态，以编剧已写入的内容为准。"
            )
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
    dynamic = RoleDynamicLayer(
        memory_texts=schedule.selected_memory_texts(materials),
        share_texts=schedule.selected_share_texts(materials),
        pass_info_texts=schedule.selected_pass_info_texts(materials),
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
    )