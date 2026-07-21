from __future__ import annotations

from ...contracts import ComposeBundle, FilledSegment, RhythmPlan, TextGenerator
from ..base import generate_text
from ..compose.assemble import build_reply_system
from .sanitize import visible_reply
from .segment import fill_segments
from .stream import StreamSink
from .typewriter import ReplyStreamer, StreamMode, TypePace

PROACTIVE_USER_CUE = (
    "[系统] 对方暂时沉默。请按「主动开口」说明，自然接一句。"
)


class ReplyDirector:
    """回复导演：写正文；对外推送交给 ReplyStreamer。"""

    name = "reply"

    def __init__(
        self,
        llm: TextGenerator | None = None,
        *,
        streamer: ReplyStreamer | None = None,
    ) -> None:
        self._llm = llm
        self.streamer = streamer or ReplyStreamer(mode="immediate")

    def run(
        self,
        *,
        user_text: str,
        rhythm: RhythmPlan,
        bundle: ComposeBundle,
        scripted_answer: str | None = None,
    ) -> tuple[FilledSegment, ...]:
        if not rhythm.should_speak:
            return ()

        if scripted_answer is not None:
            body = scripted_answer.strip()
        elif self._llm is not None:
            system = build_reply_system(
                persona_block=bundle.persona_block,
                presence_block=bundle.presence_block,
                portrait_block=bundle.portrait_block,
                on_scene_block=bundle.on_scene_block,
                memory_hint=bundle.memory_hint,
                journal_block=bundle.journal_block,
                context_block=bundle.context_block,
                scene_block=bundle.scene_block,
                mood_block=rhythm.mood or bundle.mood_block,
                include_portrait=bundle.include_portrait,
                include_memory=bundle.include_memory,
                include_architecture_note=bundle.include_architecture_note,
                proactive=bundle.proactive,
                share_title=bundle.share_title,
                segment_count=len(rhythm.segments),
                rhythm_cue=rhythm.cue,
                rhythm_tempo=rhythm.tempo,
                rhythm_reply_guide=rhythm.reply_guide,
            )
            prompt_user = user_text.strip()
            if bundle.proactive and not prompt_user:
                prompt_user = PROACTIVE_USER_CUE
            body = generate_text(self._llm, system=system, user=prompt_user)
        else:
            raise RuntimeError("reply director: need llm or scripted_answer")

        body = visible_reply(body)
        if not body:
            raise RuntimeError("reply director: empty answer")
        return fill_segments(body, rhythm)

    def push(
        self,
        segments: tuple[FilledSegment, ...] | str,
        *,
        think: str = "",
        sink: StreamSink | None = None,
    ) -> str:
        """对外推送：think -> token* -> done（模式见 ReplyStreamer）。"""
        return self.streamer.push(segments, think=think, sink=sink)

    def configure_stream(
        self,
        *,
        mode: StreamMode | None = None,
        pace: TypePace | None = None,
        sink: StreamSink | None = None,
    ) -> None:
        if mode is not None:
            self.streamer.set_mode(mode)
        if pace is not None:
            self.streamer.set_pace(pace)
        if sink is not None:
            self.streamer.bind_sink(sink)
