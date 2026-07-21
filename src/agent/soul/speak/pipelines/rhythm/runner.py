from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agent.soul.speak.io.outbound.stream import (
    SpeakAgentOutput,
    SpeakStreamChannel,
    SpeakStreamEvent,
    SpeakStreamPipeline,
    parse_agent_output,
)
from agent.soul.speak.llm.engine import SpeakLLMEngine
from agent.soul.speak.pipelines.request_driven.orchestrator import SpeakPromptBundle
from agent.soul.speak.pipelines.request_driven.orchestrator.prompt_trace import (
    get_prompt_trace,
)
from agent.soul.speak.session.queue import UserInputItem

from .compose import attach_rhythm_to_bundle, build_reply_user_text
from .contracts import RhythmPlan, ShareHandOff, ShareItem
from .directors import (
    AffectDirector,
    ArcDirector,
    OnSceneDirector,
    ReviewDirector,
    RhythmDirector,
    should_refresh_affect,
    should_refresh_on_scene,
)
from .share import (
    build_share_handoff,
    commit_share_after_speak,
    share_items_from_peek,
)
from .snapshot import RhythmSnapshot, build_rhythm_snapshot
from .state import DirectorLogBeat, RhythmSessionState, RhythmStateStore

ComposeBundleFn = Callable[..., SpeakPromptBundle]
RecordDialogueFn = Callable[..., Any]
OnTurnCompleteFn = Callable[..., Any]
PeekShareFn = Callable[[str], list[dict[str, object]]]
PopShareAtFn = Callable[[str, int], Any]
DirectorGenerateFn = Callable[[str, str], str]
TurnIndexFn = Callable[[str], int]
TypingSnapFn = Callable[[str], dict[str, object]]
WorkingMemoryFn = Callable[[str], str]


@dataclass
class RhythmPipelineRunner:
    """
    soul.speak rhythm pipeline:
    arc/affect/on_scene refresh → rhythm gate → optional compose → reply stream.
    """

    compose_bundle: ComposeBundleFn
    llm: SpeakLLMEngine
    stream_pipeline: SpeakStreamPipeline
    outbound_stream: SpeakStreamChannel
    rhythm_store: RhythmStateStore
    director_generate: DirectorGenerateFn
    current_turn_index: TurnIndexFn
    begin_turn: Callable[[str], int] | None = None
    record_dialogue: RecordDialogueFn | None = None
    on_turn_complete: OnTurnCompleteFn | None = None
    peek_share: PeekShareFn | None = None
    pop_share_at: PopShareAtFn | None = None
    typing_snapshot: TypingSnapFn | None = None
    working_memory: WorkingMemoryFn | None = None
    context_distill: WorkingMemoryFn | None = None
    affect_every_k: int = 2
    on_scene_every_k: int = 3
    _rhythm: RhythmDirector = field(init=False)
    _arc: ArcDirector = field(init=False)
    _affect: AffectDirector = field(init=False)
    _on_scene: OnSceneDirector = field(init=False)
    _review: ReviewDirector = field(init=False)

    def __post_init__(self) -> None:
        self._rhythm = RhythmDirector(self.director_generate)
        self._arc = ArcDirector(self.director_generate)
        self._affect = AffectDirector(self.director_generate)
        self._on_scene = OnSceneDirector(self.director_generate)
        self._review = ReviewDirector(self.director_generate)

    def ensure_init(self, session_id: str) -> str:
        state = self.rhythm_store.session(session_id)
        if state.inited and state.arc_text.strip():
            return state.arc_text
        share_queue = self._share_queue(session_id)
        return self._arc.init_arc(
            state,
            reason="cold_init",
            share_queue=share_queue,
            working_memory=self._wm(session_id),
        )

    def review_session(self, session_id: str) -> dict[str, Any]:
        state = self.rhythm_store.session(session_id)
        review = self._review.build_review(
            state,
            share_queue=self._share_queue(session_id),
        )
        get_prompt_trace().emit_event(
            session_id,
            label="rhythm_review",
            payload=review.snapshot(),
        )
        return review.snapshot()

    def run(self, item: UserInputItem):
        from agent.soul.speak.service import SpeakTurnResult

        sid = item.session_id.strip()
        user_text = item.user_text.strip()
        trigger = "inbound" if item.mode == "inbound" else "proactive"
        if item.mode == "inbound" and not user_text:
            raise RuntimeError("speak rhythm: empty user input")

        self.ensure_init(sid)
        state = self.rhythm_store.session(sid)
        notes = ["rhythm_pipeline"]
        turn_index = self.current_turn_index(sid) + 1
        share_queue = self._share_queue(sid)

        if should_refresh_affect(state, every_k=self.affect_every_k):
            label, valence, intensity = self._affect.refresh(
                state,
                user_text=user_text,
                trigger=trigger,
            )
            get_prompt_trace().emit_event(
                sid,
                label="rhythm_affect_refresh",
                turn_index=turn_index,
                payload={
                    "label": label,
                    "valence": valence,
                    "intensity": intensity,
                },
            )
            notes.append("rhythm_affect_refresh")

        if should_refresh_on_scene(state, every_k=self.on_scene_every_k):
            scene = self._on_scene.refresh(state)
            get_prompt_trace().emit_event(
                sid,
                label="rhythm_on_scene_refresh",
                turn_index=turn_index,
                payload=scene.snapshot(),
            )
            notes.append("rhythm_on_scene_refresh")

        typing = self._typing(sid)
        snapshot = build_rhythm_snapshot(
            state,
            user_text=user_text,
            trigger=trigger,  # type: ignore[arg-type]
            turn_index=turn_index,
            share_queue=share_queue,
            typing_active=bool(typing.get("typing_active")),
            typing_idle=bool(typing.get("typing_idle", True)),
            push_phase=str(typing.get("push_phase") or "idle"),
            brew_queue_depth=int(typing.get("brew_queue_depth") or 0),
            working_memory=self._wm(sid),
            context_distill=self._distill(sid),
        )
        get_prompt_trace().emit_event(
            sid,
            label="rhythm_snapshot",
            turn_index=turn_index,
            payload=snapshot.snapshot(),
        )

        if typing.get("typing_active") and not typing.get("typing_idle"):
            plan = RhythmPlan(
                gate="hold",
                segments=(),
                tempo="别开口",
                reply_guide="台面吐字中，别叠话",
                reason="typing_busy",
                mood="先等这句说完",
            )
            notes.append("rhythm_typing_hold")
        else:
            plan = self._rhythm.run(snapshot)

        state.mark_rhythm_beat()
        get_prompt_trace().emit_event(
            sid,
            label="rhythm_plan",
            turn_index=turn_index,
            payload=plan.snapshot(),
        )

        handoff = build_share_handoff(
            plan,
            share_queue=share_queue,
            last_shared=state.last_shared,
        )
        meta: dict[str, Any] = {
            "pipeline": "rhythm",
            "gate": plan.gate,
            "rhythm_plan": plan.snapshot(),
            "rhythm_state": state.snapshot(),
            "share_handoff": handoff.snapshot(),
            "trigger": trigger,
        }

        if not plan.should_speak:
            return self._finish_no_speak(
                SpeakTurnResult=SpeakTurnResult,
                state=state,
                item=item,
                plan=plan,
                snapshot=snapshot,
                notes=notes,
                meta=meta,
                turn_index=turn_index,
                user_text=user_text,
            )

        proactive = trigger == "proactive"
        bundle = self.compose_bundle(sid, user_text, mode=item.mode)
        attach_rhythm_to_bundle(
            bundle,
            plan=plan,
            handoff=handoff,
            proactive=proactive,
        )
        answer, events, parsed = self._generate_reply(
            sid,
            user_text=build_reply_user_text(
                user_text=user_text,
                proactive=proactive,
                plan=plan,
            ),
            bundle=bundle,
            stream=item.stream,
        )
        spoke = bool(answer.strip())
        state.record_director(
            DirectorLogBeat(
                trigger=trigger,
                gate=plan.gate,
                cue=plan.cue,
                tempo=plan.tempo,
                reply_guide=plan.reply_guide,
                reason=plan.reason,
                spoke=spoke,
            )
        )
        if not spoke:
            notes.append("rhythm_empty_answer")
            if user_text:
                state.append_history("user", user_text)
            get_prompt_trace().emit_event(
                sid,
                label="rhythm_no_speak",
                turn_index=turn_index,
                payload={"gate": plan.gate, "reason": "empty_answer"},
            )
            return SpeakTurnResult(
                session_id=sid,
                answer="",
                bundle=bundle,
                stream_events=events,
                recorded=False,
                notes=notes,
                meta=meta,
            )

        if user_text:
            state.append_history("user", user_text)
        state.append_history("agent", answer)
        committed = None
        if handoff.active:
            committed = commit_share_after_speak(
                session_id=sid,
                handoff=handoff,
                pop_share_at=self.pop_share_at,
                set_last_shared=lambda item: setattr(state, "last_shared", item),
            )
            if committed is not None:
                notes.append(f"rhythm_share_commit:{committed.item_id}")
                meta["last_shared"] = committed.snapshot()

        recorded = False
        if item.record and self.record_dialogue is not None:
            if self.begin_turn is not None:
                self.begin_turn(sid)
            self.record_dialogue(sid, user_text, answer)
            recorded = True
            if self.on_turn_complete is not None:
                session_state = (
                    parsed.session_state
                    if parsed is not None and parsed.session_state
                    else plan.continuity
                )
                self.on_turn_complete(
                    sid,
                    user_text,
                    answer,
                    turn_index,
                    session_state,
                )

        meta["rhythm_state"] = state.snapshot()
        meta["session_state"] = (
            parsed.session_state if parsed is not None else "finish"
        )
        return SpeakTurnResult(
            session_id=sid,
            answer=answer,
            bundle=bundle,
            output=parsed,
            stream_events=events,
            recorded=recorded,
            notes=notes,
            meta=meta,
        )

    def _finish_no_speak(
        self,
        *,
        SpeakTurnResult,
        state: RhythmSessionState,
        item: UserInputItem,
        plan: RhythmPlan,
        snapshot: RhythmSnapshot,
        notes: list[str],
        meta: dict[str, Any],
        turn_index: int,
        user_text: str,
    ):
        notes.append("rhythm_no_speak")
        notes.append(f"gate={plan.gate}")
        state.record_director(
            DirectorLogBeat(
                trigger=snapshot.trigger,
                gate=plan.gate,
                cue=plan.cue,
                tempo=plan.tempo,
                reply_guide=plan.reply_guide,
                reason=plan.reason,
                spoke=False,
            )
        )
        if user_text:
            state.append_history("user", user_text)
        get_prompt_trace().emit_event(
            item.session_id,
            label="rhythm_no_speak",
            turn_index=turn_index,
            payload={
                "gate": plan.gate,
                "reason": plan.reason,
                "user_text": user_text,
            },
        )
        meta["rhythm_state"] = state.snapshot()
        empty = SpeakPromptBundle(session_id=item.session_id, mode=item.mode)
        empty.meta["rhythm_gate"] = plan.gate
        empty.meta["rhythm_reply_guide"] = plan.reply_guide
        return SpeakTurnResult(
            session_id=item.session_id,
            answer="",
            bundle=empty,
            recorded=False,
            notes=notes,
            meta=meta,
        )

    def _generate_reply(
        self,
        session_id: str,
        *,
        user_text: str,
        bundle: SpeakPromptBundle,
        stream: bool,
    ) -> tuple[str, list[SpeakStreamEvent], SpeakAgentOutput | None]:
        system = bundle.build_system()
        prompt_user = user_text.strip() or "[系统] 请按本拍指导自然开口。"
        self.outbound_stream.begin_session(session_id)
        if stream:
            events = list(
                self.stream_pipeline.stream_generate(
                    self.llm,
                    session_id,
                    prompt_user,
                    system=system,
                    context="",
                )
            )
            finish = next(
                (event for event in reversed(events) if event.kind == "finish"),
                None,
            )
            answer = finish.text if finish is not None else ""
            parsed = parse_agent_output(answer) if answer.strip() else None
            spoken = (
                parsed.speak.strip()
                if parsed is not None and parsed.speak.strip()
                else answer.strip()
            )
            return spoken, events, parsed

        llm_result = self.llm.generate(prompt_user, system=system)
        answer = llm_result.text
        events = list(self.stream_pipeline.emit_parsed_output(session_id, answer))
        parsed = parse_agent_output(answer) if answer.strip() else None
        spoken = (
            parsed.speak.strip()
            if parsed is not None and parsed.speak.strip()
            else answer.strip()
        )
        return spoken, events, parsed

    def _share_queue(self, session_id: str) -> tuple[ShareItem, ...]:
        if self.peek_share is None:
            return ()
        return share_items_from_peek(self.peek_share(session_id))

    def _typing(self, session_id: str) -> dict[str, object]:
        if self.typing_snapshot is None:
            return {"typing_active": False, "typing_idle": True, "push_phase": "idle"}
        return dict(self.typing_snapshot(session_id))

    def _wm(self, session_id: str) -> str:
        if self.working_memory is None:
            return ""
        return self.working_memory(session_id).strip()

    def _distill(self, session_id: str) -> str:
        if self.context_distill is None:
            return ""
        return self.context_distill(session_id).strip()
