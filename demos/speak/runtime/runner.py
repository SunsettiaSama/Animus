from __future__ import annotations

from typing import Callable

from ..contracts import PollTickResult, RhythmPlan, TextGenerator, TurnResult
from ..directors import ComposeDirector, ReplyDirector, RhythmDirector
from ..directors.base import ComposeDirectorPort, ReplyDirectorPort, RhythmDirectorPort
from ..directors.rhythm.arc import DesireArcSupplier, SoftDesireArcSupplier
from ..directors.rhythm.init_api import (
    DesireArcInitResult,
    apply_stage_notify_patch,
    resolve_hot_supplier,
)
from ..directors.rhythm.review import SoftRhythmReviewSupplier
from ..io import SpeakInbound, SpeakOutbound
from ..io.review_store import save_review
from ..io.share_expand import NullShareExpand, ShareExpandPort
from ..stage import DesireArc, StageState
from ..stage.review import RhythmReview
from . import beat
from .clock import Clock
from .delivery import DeliveryExecutor
from .on_scene_pump import OnSceneAsyncInjector


class SpeakDemoRunner:
    """
    三导演闭环门面：
    rhythm 门控（临场异步踢刷新）→
    仅当本轮开口时 compose 按「指挥+临场」拼装 → reply。
    """

    def __init__(
        self,
        stage: StageState | None = None,
        *,
        clock: Clock | None = None,
        rhythm: RhythmDirectorPort | None = None,
        compose: ComposeDirectorPort | None = None,
        reply: ReplyDirectorPort | None = None,
        rhythm_llm: TextGenerator | None = None,
        reply_llm: TextGenerator | None = None,
        init_llm: TextGenerator | None = None,
        arc_supplier: DesireArcSupplier | None = None,
        delivery: DeliveryExecutor | None = None,
        share_expander: ShareExpandPort | None = None,
        on_scene_every_k: int = 3,
        affect_every_k: int = 2,
    ) -> None:
        self.stage: StageState = stage or StageState()
        self.session = self.stage
        self.clock = clock or Clock()
        self.stage.ensure_timeline(self.clock)
        self._init_llm = init_llm or rhythm_llm
        self._arc_supplier = arc_supplier
        if self._arc_supplier is None and self._init_llm is not None:
            self._arc_supplier = SoftDesireArcSupplier(self._init_llm)
        if rhythm is None and rhythm_llm is None:
            raise RuntimeError(
                "SpeakDemoRunner: 节奏必须注入 SoftChannel / LLM，禁止硬编码阈值回退"
            )
        self.rhythm: RhythmDirectorPort = rhythm or RhythmDirector(
            llm=rhythm_llm,
            arc_supplier=self._arc_supplier,
            on_scene_every_k=on_scene_every_k,
            affect_every_k=affect_every_k,
        )
        self.compose: ComposeDirectorPort = compose or ComposeDirector()
        self.reply: ReplyDirectorPort = reply or ReplyDirector(llm=reply_llm)
        self.delivery = delivery or DeliveryExecutor(sleep=False)
        self.delivery.on_typing_start = lambda: self.stage.set_floor("typing")
        self.delivery.on_typing_end = lambda: self.stage.set_floor("awaiting_user")
        self.inbound = SpeakInbound(self.stage)
        self.outbound = SpeakOutbound(
            streamer=getattr(self.reply, "streamer", None),
            delivery=self.delivery,
        )
        on_scene_llm = rhythm_llm or self._init_llm
        if on_scene_llm is None:
            raise RuntimeError("SpeakDemoRunner: 临场异步泵需要 rhythm_llm")
        self.on_scene_pump = OnSceneAsyncInjector(
            on_scene_llm,
            self.inbound,
            every_k=on_scene_every_k,
        )
        self._share_expander = share_expander or NullShareExpand()
        self._scripted: dict[str, str] = {}
        self._proactive_script: list[str] = []
        self._proactive_script_idx = 0
        self._inited = False
        self._review_llm = self._init_llm or rhythm_llm

    def bind_script(self, mapping: dict[str, str]) -> None:
        self._scripted = {k.strip(): v for k, v in mapping.items()}

    def bind_proactive_script(self, lines: list[str] | tuple[str, ...]) -> None:
        self._proactive_script = [line.strip() for line in lines if line.strip()]
        self._proactive_script_idx = 0

    def _arc_stage_view(self) -> dict:
        return beat.stage_view(
            self.stage,
            "",
            clock=self.clock,
            trigger="poll",
            poll_index=self.stage.poll_index,
        )

    def init_directors(
        self,
        *,
        supplier: DesireArcSupplier | None = None,
        reason: str = "cold_init",
    ) -> DesireArc:
        """冷启动 init：拟定并挂载本轮对话弧。"""
        arc = self.rhythm.init(
            self.stage,
            supplier=supplier or self._arc_supplier,
            reason=reason,
            previous=None,
        )
        self.on_scene_pump.poll_and_kick(self.stage)
        self._inited = True
        return arc

    def ensure_init(self) -> DesireArc:
        if self.stage.desire_arc is not None and self._inited:
            return self.stage.desire_arc
        return self.init_directors()

    def review_session(self, *, persist: bool = True) -> RhythmReview:
        """
        会话结束伪学习：浓缩 abstract + 复盘 summary，写回 stage 并可选落盘。
        """
        if self._review_llm is None:
            raise RuntimeError("review_session: 需要 init/rhythm LLM")
        review = SoftRhythmReviewSupplier(self._review_llm).build_review(self.stage)
        self.stage.set_rhythm_review(review)
        if persist:
            save_review(self.stage.session_id, review)
        return review

    def hot_init_desire_arc(
        self,
        *,
        reason: str = "external",
        supplier: DesireArcSupplier | None = None,
        mutate: Callable[[StageState], None] | None = None,
        arc_text: str | None = None,
    ) -> DesireArcInitResult:
        if mutate is not None:
            mutate(self.stage)
        resolved = resolve_hot_supplier(
            supplier=supplier,
            arc_text=arc_text,
            default=self._arc_supplier,
        )
        arc = self.rhythm.hot_init(
            self.stage,
            supplier=resolved,
            reason=reason,
        )
        self._inited = True
        return DesireArcInitResult(
            arc=arc,
            hot=True,
            reason=reason,
            stage=self._arc_stage_view(),
        )

    def notify_stage_changed(
        self,
        *,
        reason: str = "external.notify",
        agent_status: str | None = None,
        agent_presence: str | None = None,
        affect_intensity: float | None = None,
        affect_label: str | None = None,
        affect_valence: str | None = None,
        share_title: str | None = None,
        share_detail: str = "",
        share_urgency: float = 0.6,
        reinit_arc: bool = True,
        supplier: DesireArcSupplier | None = None,
        arc_text: str | None = None,
    ) -> DesireArcInitResult | None:
        apply_stage_notify_patch(
            self.stage,
            agent_status=agent_status,
            agent_presence=agent_presence,
            affect_intensity=affect_intensity,
            affect_label=affect_label,
            affect_valence=affect_valence,
            share_title=share_title,
            share_detail=share_detail,
            share_urgency=share_urgency,
        )
        if not reinit_arc:
            return None
        return self.hot_init_desire_arc(
            reason=reason,
            supplier=supplier,
            arc_text=arc_text,
        )

    def _next_proactive_script(self) -> str | None:
        if not self._proactive_script:
            return None
        line = self._proactive_script[self._proactive_script_idx % len(self._proactive_script)]
        self._proactive_script_idx += 1
        return line

    def _typing_busy(self) -> bool:
        if self.stage.floor_phase == "typing":
            return True
        streamer = self.delivery.streamer or getattr(self.reply, "streamer", None)
        return bool(streamer is not None and getattr(streamer, "busy", False))

    def run_turn(
        self,
        user_text: str,
        *,
        share_wants: bool = False,
        silence_armed: bool = False,
        deliver: bool = True,
    ) -> TurnResult:
        text = user_text.strip()
        if not text:
            raise RuntimeError("speak demo: empty user text")

        self.ensure_init()
        self.stage.mark_user(self.clock)
        snapshot, rhythm_plan, bundle, handoff = beat.rhythm_tick(
            stage=self.stage,
            clock=self.clock,
            rhythm=self.rhythm,
            compose=self.compose,
            on_scene_pump=self.on_scene_pump,
            share_expander=self._share_expander,
            user_text=text,
            trigger="user",
            share_wants=share_wants,
            silence_armed=silence_armed,
        )

        arc_preview = "-"
        if snapshot.desire_arc is not None:
            arc_preview = snapshot.desire_arc.one_line()
        notes = [
            "trigger=user",
            f"gate={rhythm_plan.gate}",
            f"share_tag={rhythm_plan.share_tag}",
            f"share_id={rhythm_plan.share_id or '-'}",
            f"tempo={rhythm_plan.tempo or '-'}",
            f"reply_guide={rhythm_plan.reply_guide or '-'}",
            f"rhythm_reason={rhythm_plan.reason or '-'}",
            f"cue={rhythm_plan.cue or '-'}",
            f"floor={snapshot.floor_phase}",
            f"share_queue={len(self.stage.share_queue)}",
            f"affect={self.stage.affect.label}",
            f"on_scene={self.stage.on_scene.one_line() if self.stage.on_scene.ready else '-'}",
            f"arc={arc_preview}",
        ]
        if bundle is not None:
            notes.extend(bundle.notes)

        if bundle is None:
            segments, answer = (), ""
            notes.append("no_compose_listen_or_hold")
        else:
            segments, answer = beat.deliver_reply(
                reply=self.reply,
                delivery=self.delivery,
                user_text=text,
                rhythm_plan=rhythm_plan,
                bundle=bundle,
                scripted=self._scripted.get(text),
                deliver=deliver,
            )
        spoke = bool(rhythm_plan.should_speak and answer.strip())
        beat.record_director(self.stage, "user", rhythm_plan, spoke=spoke)

        if spoke:
            self.stage.append_turn(text, answer, clock=self.clock)
            self.stage.mark_agent(self.clock, proactive=False)
            beat.commit_share(self.stage, handoff, spoke=True)
        else:
            self.stage.append_user_only(text, clock=self.clock)
            notes.append("no_speak_or_empty")

        return TurnResult(
            session_id=snapshot.session_id,
            turn_index=snapshot.turn_index,
            trigger="user",
            user_text=text,
            rhythm=rhythm_plan,
            bundle=bundle,
            segments=segments,
            answer=answer,
            notes=tuple(notes),
            stage=beat.stage_view(
                self.stage,
                text,
                clock=self.clock,
                trigger="user",
                poll_index=snapshot.poll_index,
            ),
        )

    def poll_once(
        self,
        *,
        share_wants: bool = False,
        silence_armed: bool = False,
        deliver: bool = True,
    ) -> PollTickResult:
        self.ensure_init()
        poll_index = self.stage.bump_poll()

        if self._typing_busy():
            rhythm_plan = RhythmPlan(
                gate="hold",
                segments=(),
                cue="台面吐字中",
                tempo="先停住",
                reply_guide="打字机还在消费，不要叠开新口",
                reason="floor_typing",
            )
            beat.record_director(self.stage, "poll", rhythm_plan, spoke=False)
            stage_view = beat.stage_view(
                self.stage,
                "",
                clock=self.clock,
                trigger="poll",
                poll_index=poll_index,
            )
            return PollTickResult(
                poll_index=poll_index,
                idle_ms=self.stage.idle_ms(self.clock),
                rhythm=rhythm_plan,
                spoke=False,
                turn=None,
                stage=stage_view,
            )

        snapshot, rhythm_plan, bundle, handoff = beat.rhythm_tick(
            stage=self.stage,
            clock=self.clock,
            rhythm=self.rhythm,
            compose=self.compose,
            on_scene_pump=self.on_scene_pump,
            share_expander=self._share_expander,
            user_text="",
            trigger="poll",
            share_wants=share_wants,
            silence_armed=silence_armed,
            poll_index=poll_index,
        )
        stage_view = beat.stage_view(
            self.stage,
            "",
            clock=self.clock,
            trigger="poll",
            poll_index=poll_index,
        )
        if bundle is None or not rhythm_plan.should_speak:
            beat.record_director(self.stage, "poll", rhythm_plan, spoke=False)
            return PollTickResult(
                poll_index=poll_index,
                idle_ms=snapshot.idle_ms,
                rhythm=rhythm_plan,
                spoke=False,
                turn=None,
                stage=stage_view,
            )

        arc_preview = "-"
        if snapshot.desire_arc is not None:
            arc_preview = snapshot.desire_arc.one_line()
        notes = [
            "trigger=poll",
            f"gate={rhythm_plan.gate}",
            f"share_tag={rhythm_plan.share_tag}",
            f"share_id={rhythm_plan.share_id or '-'}",
            f"tempo={rhythm_plan.tempo or '-'}",
            f"reply_guide={rhythm_plan.reply_guide or '-'}",
            f"idle_ms={snapshot.idle_ms}",
            f"floor={snapshot.floor_phase}",
            f"rhythm_reason={rhythm_plan.reason or '-'}",
            f"cue={rhythm_plan.cue or '-'}",
            f"share_queue={len(self.stage.share_queue)}",
            f"affect={self.stage.affect.label}",
            f"on_scene={self.stage.on_scene.one_line()}",
            f"arc={arc_preview}",
            *bundle.notes,
        ]
        segments, answer = beat.deliver_reply(
            reply=self.reply,
            delivery=self.delivery,
            user_text="",
            rhythm_plan=rhythm_plan,
            bundle=bundle,
            scripted=self._next_proactive_script(),
            deliver=deliver,
        )
        spoke = bool(answer.strip())
        beat.record_director(self.stage, "poll", rhythm_plan, spoke=spoke)

        if spoke:
            self.stage.append_turn("", answer, clock=self.clock)
            self.stage.mark_agent(self.clock, proactive=True)
            beat.commit_share(self.stage, handoff, spoke=True)
        else:
            notes.append("proactive_empty")

        turn = TurnResult(
            session_id=snapshot.session_id,
            turn_index=snapshot.turn_index,
            trigger="poll",
            user_text="",
            rhythm=rhythm_plan,
            bundle=bundle,
            segments=segments,
            answer=answer,
            notes=tuple(notes),
            stage=stage_view,
        )
        return PollTickResult(
            poll_index=poll_index,
            idle_ms=snapshot.idle_ms,
            rhythm=rhythm_plan,
            spoke=spoke,
            turn=turn,
            stage=beat.stage_view(
                self.stage,
                "",
                clock=self.clock,
                trigger="poll",
                poll_index=poll_index,
            ),
        )
