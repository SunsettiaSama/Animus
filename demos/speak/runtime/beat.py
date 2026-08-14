from __future__ import annotations

from typing import Any

from ..contracts import (
    Clock,
    ComposeBundle,
    FilledSegment,
    RhythmPlan,
    ShareHandOff,
    TurnTrigger,
)
from ..directors.base import ComposeDirectorPort, ReplyDirectorPort, RhythmDirectorPort
from ..io.share_expand import ShareExpandPort
from ..stage import DesireArc, StageSnapshot, StageState, capture_stage
from ..stage.director_log import DirectorBeat
from .delivery import DeliveryExecutor
from .on_scene_pump import OnSceneAsyncInjector
from .share import build_share_handoff, commit_share_after_speak


def prepare_beat_stage(
    stage: StageState,
    *,
    share_wants: bool = False,
    silence_armed: bool = False,
) -> None:
    """拍前副作用（原顶层 build_snapshot）；不污染纯 capture_stage。"""
    if silence_armed:
        stage.silence_armed = True
    if share_wants and not stage.share_pending:
        stage.enqueue_share("有话想接", detail="外部分享欲信号")


def capture_beat(
    stage: StageState,
    user_text: str,
    *,
    clock: Clock,
    trigger: TurnTrigger,
    poll_index: int | None = None,
    share_wants: bool = False,
    silence_armed: bool = False,
    push_phase: str = "idle",
) -> StageSnapshot:
    prepare_beat_stage(stage, share_wants=share_wants, silence_armed=silence_armed)
    return capture_stage(
        stage,
        user_text,
        clock=clock,
        trigger=trigger,
        push_phase=push_phase,
        poll_index=poll_index,
    )


def record_director(
    stage: StageState,
    trigger: str,
    plan: RhythmPlan,
    *,
    spoke: bool,
) -> None:
    stage.record_director(
        DirectorBeat(
            trigger=trigger,  # type: ignore[arg-type]
            gate=plan.gate,
            cue=plan.cue,
            tempo=plan.tempo,
            reply_guide=plan.reply_guide,
            reason=plan.reason,
            spoke=spoke,
        )
    )


def rhythm_tick(
    *,
    stage: StageState,
    clock: Clock,
    rhythm: RhythmDirectorPort,
    compose: ComposeDirectorPort,
    on_scene_pump: OnSceneAsyncInjector,
    share_expander: ShareExpandPort,
    user_text: str,
    trigger: TurnTrigger,
    share_wants: bool = False,
    silence_armed: bool = False,
    poll_index: int | None = None,
) -> tuple[StageSnapshot, RhythmPlan, ComposeBundle | None, ShareHandOff]:
    """
    临场异步：先 drain/kick → rhythm 门控 → 再 drain 供拼装。
    仅当本轮开口时 compose。
    """
    on_scene_pump.poll_and_kick(stage)
    if rhythm.affect_due(stage):
        rhythm.refresh_affect(stage, user_text=user_text, trigger=trigger)
    snapshot = capture_beat(
        stage,
        user_text,
        clock=clock,
        trigger=trigger,
        share_wants=share_wants,
        silence_armed=silence_armed,
        poll_index=poll_index,
    )
    rhythm_plan = rhythm.run(snapshot)
    stage.mark_rhythm_beat()
    on_scene_pump.drain()
    if not rhythm_plan.should_speak:
        return snapshot, rhythm_plan, None, ShareHandOff(tag="none")
    handoff = build_share_handoff(stage, rhythm_plan, expander=share_expander)
    bundle = compose.run(
        stage,
        snapshot,
        rhythm=rhythm_plan,
        share_handoff=handoff,
    )
    return snapshot, rhythm_plan, bundle, handoff


def commit_share(stage: StageState, handoff: ShareHandOff, *, spoke: bool) -> None:
    if not spoke or not handoff.active:
        return
    taken = commit_share_after_speak(stage, handoff)
    if taken is None:
        return
    if handoff.tag == "share":
        stage.set_affect(label="说完轻松一点")
        stage.set_desire_arc(
            DesireArc(
                text=(
                    f"刚提过「{taken.title}」，先听着；"
                    "下一拍空闲若还想展开，可用 share_tag=expand。"
                ),
                source="external",
            )
        )


def deliver_reply(
    *,
    reply: ReplyDirectorPort,
    delivery: DeliveryExecutor,
    user_text: str,
    rhythm_plan: RhythmPlan,
    bundle: ComposeBundle,
    scripted: str | None,
    deliver: bool,
) -> tuple[tuple[FilledSegment, ...], str]:
    segments = reply.run(
        user_text=user_text,
        rhythm=rhythm_plan,
        bundle=bundle,
        scripted_answer=scripted,
    )
    if deliver and segments:
        reply_streamer = getattr(reply, "streamer", None)
        if delivery.streamer is None and reply_streamer is not None:
            delivery.streamer = reply_streamer
        think = " | ".join(
            part
            for part in (rhythm_plan.tempo, rhythm_plan.cue, rhythm_plan.reply_guide)
            if part.strip()
        )
        answer = delivery.execute(segments, think=think)
    else:
        answer = "\n".join(seg.text for seg in segments)
    return segments, answer


def stage_view(
    stage: StageState,
    user_text: str,
    *,
    clock: Clock,
    trigger: TurnTrigger,
    poll_index: int | None = None,
) -> dict[str, Any]:
    return capture_beat(
        stage,
        user_text,
        clock=clock,
        trigger=trigger,
        poll_index=poll_index,
    ).snapshot()
