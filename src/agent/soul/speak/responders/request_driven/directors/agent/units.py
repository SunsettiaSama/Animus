from __future__ import annotations

from dataclasses import dataclass

from infra.agent.unit import Unit


@dataclass
class RhythmCardUnit(Unit):
    """导演节奏卡片：仅上下文，不硬改 gate。"""

    card: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            self.kind = "rhythm_card"
        if not self.source:
            self.source = "director"

    def render(self) -> str:
        text = self.card.strip()
        return f"[节奏卡片]\n{text}" if text else ""


@dataclass
class FateDiceUnit(Unit):
    """命运骰卡片：开口欲软评分（0~100），只注入上下文。"""

    roll: int = 0
    tendency: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            self.kind = "fate_dice"
        if not self.source:
            self.source = "director"

    def render(self) -> str:
        tendency = self.tendency.strip()
        lines = [
            "[命运骰·开口欲]",
            f"评分={int(self.roll)}/100",
        ]
        if tendency:
            lines.append(f"倾向={tendency}")
        lines.append("说明：0~10 非常不想说话；90~100 非常想说话；软扰动，勿硬切 gate。")
        return "\n".join(lines)


@dataclass
class PresenceUnit(Unit):
    """编剧临场状态 unit：供导演编排消费，不由导演撰写。"""

    mood: str = ""
    brief: str = ""
    speak_desire: int | None = None
    fate_tendency: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            self.kind = "presence"
        if not self.source:
            self.source = "screenwriter"

    def render(self) -> str:
        lines = ["[编剧·临场状态]"]
        if self.mood.strip():
            lines.append(f"心情={self.mood.strip()}")
        if self.speak_desire is not None:
            band = self.fate_tendency.strip() or "—"
            lines.append(f"开口欲={int(self.speak_desire)}/100（{band}）")
        if self.brief.strip():
            lines.append(f"简述={self.brief.strip()}")
        return "\n".join(lines) if len(lines) > 1 else ""


@dataclass
class PollTickUnit(Unit):
    """轮询时间元数据空卡：告知导演本拍时间与上一拍是否空转。"""

    poll_seq: int = 0
    now_ts: float = 0.0
    sec_since_user: float | None = None
    sec_since_agent: float | None = None
    last_idle_note: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            self.kind = "poll_tick"
        if not self.source:
            self.source = "director"

    def render(self) -> str:
        lines = [
            "[轮询空卡·时间元数据]",
            f"poll_seq={int(self.poll_seq)}",
            f"now_ts={float(self.now_ts):.3f}",
        ]
        if self.sec_since_user is not None:
            lines.append(f"sec_since_user={float(self.sec_since_user):.1f}")
        if self.sec_since_agent is not None:
            lines.append(f"sec_since_agent={float(self.sec_since_agent):.1f}")
        note = self.last_idle_note.strip()
        if note:
            lines.append(f"上一拍={note}")
        else:
            lines.append("上一拍=（无空转记录）")
        return "\n".join(lines)


@dataclass
class AgentDeliveryTraceUnit(Unit):
    """角色出站轨迹：让导演知道已交付内容或仍在生成的交接。"""

    entries: tuple[dict[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.kind:
            self.kind = "agent_delivery_trace"
        if not self.source:
            self.source = "speak_delivery"

    def render(self) -> str:
        if not self.entries:
            return ""
        lines = [
            "[角色交付轨迹｜即时]",
            "说明：此卡是真实出站状态；generating 表示已决定交付、角色正文仍在生成；"
            "同一交接已在途时保持当前预约即可。",
        ]
        for entry in self.entries[-6:]:
            status = str(entry.get("status") or "").strip() or "unknown"
            trigger_id = str(entry.get("trigger_id") or "").strip() or "—"
            text = str(entry.get("text") or "").strip()
            lines.append(f"- status={status} trigger={trigger_id}")
            if text:
                lines.append(f"  内容={text[:360]}")
        return "\n".join(lines)


@dataclass
class UserSilenceUnit(Unit):
    """无用户输入元数据卡：累加「时间——多角度观察」；交叙事合理化。"""

    entries: tuple[str, ...] = ()
    silence_armed: bool = False

    def __post_init__(self) -> None:
        if not self.kind:
            self.kind = "user_silence"
        if not self.source:
            self.source = "director"

    @staticmethod
    def canonical_user_text(*, entry_count: int = 0) -> str:
        n = max(0, int(entry_count))
        if n <= 0:
            return "（系统：用户当前无新输入；观察记录已交给叙事合理化，勿臆测唯一意图。）"
        return (
            f"（系统：用户侧连续无输入观察 {n} 条；请结合叙事舞台与临场事件把握在场，"
            "勿臆测用户未言明的唯一意图。）"
        )

    def render(self) -> str:
        if not self.entries:
            return ""
        lines = ["[无用户输入卡·元数据]", *self.entries]
        if self.silence_armed:
            lines.append("silence_armed=true")
        lines.append(
            "说明：多角度观察记录；叙事侧合理化「静默」本身（场面/物件/角色侧），"
            "避免描写用户外在动作；导演结合叙事校验临场并拟定下一节奏。"
            "通道：用户↔世界目前仅文字发言/静默可观测。"
        )
        return "\n".join(lines)


@dataclass
class UserStageUnit(Unit):
    """用户舞台：外在身份与正在做的事（不含意图字段）。"""

    user_identity: str = ""
    user_activity: str = ""
    interaction_mode: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            self.kind = "user_stage"
        if not self.source:
            self.source = "screenwriter"

    def render(self) -> str:
        identity = self.user_identity.strip()
        activity = self.user_activity.strip()
        mode = self.interaction_mode.strip()
        if not identity and not activity and not mode:
            return ""
        lines = ["[用户舞台｜叙事导演]"]
        if mode:
            lines.append(f"交互通道={mode}")
            lines.append(
                "通道说明：用户↔世界目前仅文字发言/静默可观测；"
                "编剧可合理化已有说法，静默时避免描写用户动作，无说法勿杜撰。"
            )
        if identity:
            lines.append(f"身份={identity}")
        if activity:
            lines.append(f"正在做={activity}")
        return "\n".join(lines)


@dataclass
class SceneEventUnit(Unit):
    """临场事件：客观论文语气；与角色主观无关（附带，主注入见 PlotFlowUnit）。"""

    scene_event: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            self.kind = "scene_event"
        if not self.source:
            self.source = "screenwriter"

    def render(self) -> str:
        event = self.scene_event.strip()
        if not event:
            return ""
        return "[临场事件｜客观纪要]\n" + event


@dataclass
class MemoryBufferCardUnit(Unit):
    """离散记忆 unit 卡：供导演工具/编排按 unit_id 引用。"""

    memory_id: str = ""
    body: str = ""
    origin: str = ""
    has_embedding: bool = False

    def __post_init__(self) -> None:
        if not self.kind:
            self.kind = "memory_buffer"
        if not self.source:
            self.source = "compose_manager"
        mid = self.memory_id.strip()
        if mid:
            self.unit_id = mid

    def render(self) -> str:
        mid = self.memory_id.strip()
        body = self.body.strip()
        if not mid or not body:
            return ""
        lines = [f"[记忆unit:{mid}]"]
        if self.origin.strip():
            lines.append(f"source={self.origin.strip()}")
        if self.has_embedding:
            lines.append("embedding=yes")
        lines.append(body)
        return "\n".join(lines)


@dataclass
class PlotFlowUnit(Unit):
    """剧情流 unit：编剧主表注入口，随时可塞进导演/角色上下文。"""

    chronicle: str = ""
    focus_now: str = ""
    next_push: str = ""
    beats_text: str = ""
    arc_text: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            self.kind = "plot_flow"
        if not self.source:
            self.source = "screenwriter"

    @classmethod
    def from_flow(cls, flow, *, plot_arc=None) -> PlotFlowUnit | None:
        if flow is None or not getattr(flow, "ready", False):
            if plot_arc is None or not getattr(plot_arc, "ready", False):
                return None
        rendered = flow.render_for_inject() if flow is not None and getattr(flow, "ready", False) else ""
        arc_body = ""
        if plot_arc is not None and getattr(plot_arc, "ready", False):
            arc_body = plot_arc.render_for_inject()
        if not rendered.strip() and not arc_body.strip():
            return None
        recent = ""
        beats = list(getattr(flow, "beats", None) or []) if flow is not None else []
        if beats:
            recent = "\n".join(
                f"- [{b.kind}] {b.text.strip()}" for b in beats[-4:] if str(b.text).strip()
            )
        return cls(
            chronicle=str(getattr(flow, "chronicle", "") or "").strip() if flow is not None else "",
            focus_now=str(getattr(flow, "focus_now", "") or "").strip() if flow is not None else "",
            next_push=str(getattr(flow, "next_push", "") or "").strip() if flow is not None else "",
            beats_text=recent,
            arc_text=arc_body,
        )

    def render(self) -> str:
        lines: list[str] = []
        if self.arc_text.strip():
            lines.append(self.arc_text.strip())
        flow_lines = ["[剧情流]"]
        if self.chronicle.strip():
            flow_lines.append(f"轨迹={self.chronicle.strip()}")
        if self.focus_now.strip():
            flow_lines.append(f"戏眼={self.focus_now.strip()}")
        if self.next_push.strip():
            flow_lines.append(f"可推={self.next_push.strip()}")
        if self.beats_text.strip():
            flow_lines.append("近拍：")
            flow_lines.append(self.beats_text.strip())
        if len(flow_lines) > 1:
            lines.extend(flow_lines)
        return "\n".join(lines)


@dataclass
class InteractionPlanUnit(Unit):
    """交互单元注入：当前角色接下来 k 拍打算做什么。"""

    intent: str = ""
    evidence: str = ""
    span_polls: int = 0
    status: str = ""
    arc_summary: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            self.kind = "interaction_unit"
        if not self.source:
            self.source = "screenwriter"

    def render(self) -> str:
        intent = self.intent.strip()
        if not intent:
            return ""
        lines = ["[交互单元｜角色行动步骤·与用户大纲无关]"]
        if self.arc_summary.strip():
            lines.append(f"角色大纲={self.arc_summary.strip()}")
        lines.append(f"角色打算={intent}")
        if self.span_polls > 0:
            lines.append(f"覆盖轮询k={int(self.span_polls)}（约{max(1, int(self.span_polls) // 2)}次开口）")
        if self.status.strip():
            lines.append(f"状态={self.status.strip()}")
        if self.evidence.strip():
            lines.append(f"依据={self.evidence.strip()[:200]}")
        return "\n".join(lines)