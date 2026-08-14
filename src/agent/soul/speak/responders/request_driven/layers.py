from __future__ import annotations

from dataclasses import dataclass

from agent.soul.speak.responders.request_driven.orchestrator.compose_manager.projectors.dynamic_layer import (
    DynamicLayerMaterials,
    DynamicLayerSchedule,
)
from agent.soul.speak.responders.request_driven.orchestrator.compose_manager.projectors.role_view import (
    RoleContextView,
)

# 交付节奏协议（面向推流分段）；严禁写入 worker 工具名 / 具体 action 目录。
_ROLE_PROTOCOL_HINT = (
    "你通过交错的交付块组织开口（可多次）：\n"
    "<speak context>一句或一段台词</speak context>\n"
    "<speak action>emit</speak action>\n"
    "可选节奏：\n"
    "<speak action>wait 2</speak action>（短暂停顿，秒）\n"
    "<speak action>silence 3</speak action>（静默，秒）\n"
    "<body action>姿态或神态</body action>\n"
    "规则：context 可连续多条，由 emit 分段发出；不要输出 JSON、ReAct 或工具调用。"
)

# 轻量求助：只允许自然语言目标；具体怎么做由 io→worker 分流，不进角色提示。
_ROLE_HELP_HINT = (
    "若对话里确需查证或整理一点轻量资料，可另写一行："
    "<ask help>用自然语言写清你想弄清什么</ask help>。"
    "系统会转交后台；你不要写步骤、工具名或操作指令，也不要假装已经查完。"
)


@dataclass(frozen=True)
class RoleStaticLayer:
    """静态层：交付协议 + 可选求助提示。人格壳由 base_system 提供。"""

    protocol: str = _ROLE_PROTOCOL_HINT
    help_hint: str = _ROLE_HELP_HINT


@dataclass(frozen=True)
class RoleDynamicLayer:
    """动态层：仅含 Director 已调度选中的可注入内容。"""

    memory_texts: tuple[str, ...] = ()
    share_texts: tuple[str, ...] = ()
    pass_info_texts: tuple[str, ...] = ()
    behavior_guide: str = ""
    script_hint: str = ""
    schedule_reason: str = ""
    help_observations: tuple[str, ...] = ()


@dataclass(frozen=True)
class RolePromptLayers:
    static: RoleStaticLayer
    dynamic: RoleDynamicLayer
    dialogue_frame: str = ""
    user_text: str = ""

    def render_system_extra(self) -> str:
        parts: list[str] = [
            self.static.protocol.strip(),
            self.static.help_hint.strip(),
        ]
        if self.dialogue_frame.strip():
            parts.append(self.dialogue_frame.strip())
        dyn_blocks: list[str] = []
        if self.dynamic.behavior_guide.strip():
            dyn_blocks.append(
                "【动态层·行为指引｜上轮导演对当前轮的预测】\n"
                + self.dynamic.behavior_guide.strip()
            )
        if self.dynamic.script_hint.strip():
            dyn_blocks.append(
                "【动态层·剧本提示｜上轮导演对当前轮的预测】\n"
                + self.dynamic.script_hint.strip()
            )
        if self.dynamic.memory_texts:
            dyn_blocks.append(
                "【动态层·记忆｜导演调度】\n"
                + "\n".join(f"- {t}" for t in self.dynamic.memory_texts)
            )
        if self.dynamic.share_texts:
            dyn_blocks.append(
                "【动态层·分享｜导演调度】\n"
                + "\n".join(f"- {t}" for t in self.dynamic.share_texts)
            )
        if self.dynamic.pass_info_texts:
            dyn_blocks.append(
                "【动态层·导演传递信息｜导演调度】\n"
                + "\n".join(f"- {t}" for t in self.dynamic.pass_info_texts)
            )
        if self.dynamic.help_observations:
            dyn_blocks.append(
                "【动态层·后台回传｜仅作参考，勿复述机制】\n"
                + "\n".join(f"- {t}" for t in self.dynamic.help_observations)
            )
        if dyn_blocks:
            header = "【动态层】以下内容由导演调度/预测或后台回传注入；未列出的材料不得擅自当作已注入。"
            if self.dynamic.schedule_reason.strip():
                header += f"\n调度理由：{self.dynamic.schedule_reason.strip()}"
            parts.append(header + "\n\n" + "\n\n".join(dyn_blocks))
        else:
            parts.append("【动态层】本轮导演未调度记忆/分享/传递信息。")
        return "\n\n".join(p for p in parts if p.strip())


def build_dialogue_frame(view: RoleContextView) -> str:
    chunks: list[str] = []
    if view.history_distilled:
        chunks.append("【对话轨迹·压缩】\n" + "\n".join(view.history_distilled[-6:]))
    if view.working_turns:
        lines = [f"用户：{u}\n你：{a}" for u, a in view.working_turns[-4:]]
        chunks.append("【对话轨迹·未压缩】\n" + "\n".join(lines))
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
) -> RolePromptLayers:
    dynamic = RoleDynamicLayer(
        memory_texts=schedule.selected_memory_texts(materials),
        share_texts=schedule.selected_share_texts(materials),
        pass_info_texts=schedule.selected_pass_info_texts(materials),
        behavior_guide=behavior_guide.strip(),
        script_hint=script_hint.strip(),
        schedule_reason=schedule.reason,
        help_observations=tuple(t for t in help_observations if str(t).strip()),
    )
    return RolePromptLayers(
        static=RoleStaticLayer(),
        dynamic=dynamic,
        dialogue_frame=build_dialogue_frame(view),
        user_text=user_text.strip(),
    )
