from __future__ import annotations

from ..contracts import PollTickResult, TurnResult
from ..directors.reply.stream import StreamEvent
from ..runtime.poller import PollSample


class AgentLineSink:
    """轻量控制台 sink：token 实时刷出；think 默认不渲染。"""

    def __init__(self, *, show_think: bool = False) -> None:
        self.show_think = show_think
        self._started = False
        self.streamed = False

    def reset(self) -> None:
        self._started = False
        self.streamed = False

    def on_event(self, event: StreamEvent) -> None:
        if event.kind == "think":
            if self.show_think and event.text.strip():
                print(f"  think> {event.text.strip()}", flush=True)
            return
        if event.kind == "token":
            if not self._started:
                print("agent> ", end="", flush=True)
                self._started = True
                self.streamed = True
            print(event.text, end="", flush=True)
            return
        if event.kind == "done" and self._started:
            print(flush=True)


def _clip(text: str, limit: int) -> str:
    body = " ".join(text.strip().split())
    if len(body) <= limit:
        return body
    return body[: max(0, limit - 1)] + "…"


def _arc_preview(stage: dict | None, *, limit: int = 56) -> str:
    if not stage:
        return "-"
    desire = stage.get("desire_arc") or {}
    return _clip(str(desire.get("text") or ""), limit) or "-"


def _stage_line(stage: dict | None) -> str:
    if not stage:
        return "stage=-"
    affect = stage.get("affect") or {}
    share_n = len(stage.get("share_queue") or [])
    on_scene = stage.get("on_scene") or {}
    focus = on_scene.get("focus") or "-"
    scene_txt = _clip(str(on_scene.get("text") or ""), 28)
    streak = int(stage.get("gate_streak") or 0)
    last_gate = str(stage.get("last_gate") or "")
    streak_bit = ""
    if streak >= 3 and last_gate:
        streak_bit = f" streak={last_gate}×{streak}"
    valence = str(affect.get("valence") or "")
    intensity = affect.get("intensity")
    affect_tail = ""
    if valence and valence != "neutral":
        affect_tail += f"/{valence}"
    if isinstance(intensity, int | float):
        affect_tail += f"/{float(intensity):.2f}"
    return (
        f"share={share_n} "
        f"affect={affect.get('label') or '-'}{affect_tail} "
        f"on_scene={focus}:{scene_txt or '-'} "
        f"arc={_arc_preview(stage)}"
        f"{streak_bit}"
    )


def print_banner(mode: str, session_id: str, *, share_n: int, affect_label: str) -> None:
    print(
        f"[speak-demo] mode={mode} session={session_id} "
        f"share={share_n} affect={affect_label or '-'}",
        flush=True,
    )


def print_arc(source: str, text: str) -> None:
    print("[init] dialogue_arc", flush=True)
    print(f"  source={source}", flush=True)
    print(f"  {_clip(text, 200)}", flush=True)


def print_turn_meta(result: TurnResult) -> None:
    print(
        f"  rhythm  gate={result.rhythm.gate} "
        f"tempo={_clip(result.rhythm.tempo or '-', 40)}",
        flush=True,
    )
    print(
        f"  guide  {_clip(result.rhythm.reply_guide or result.rhythm.cue or '-', 72)}",
        flush=True,
    )
    print(f"  {_stage_line(result.stage)}", flush=True)


def print_user_turn(
    user_text: str,
    result: TurnResult,
    *,
    echo_user: bool = True,
    skip_answer: bool = False,
) -> None:
    print(flush=True)
    print(f"── user · turn {result.turn_index} ──", flush=True)
    if echo_user:
        print(f"you> {user_text}", flush=True)
    if not skip_answer:
        if result.answer.strip():
            print(f"agent> {result.answer.strip()}", flush=True)
        else:
            print("agent> （未开口）", flush=True)
    print_turn_meta(result)


def print_poll_sample(sample: PollSample, *, skip_answer: bool = False) -> None:
    p = sample.probability
    if not sample.sampled:
        print(
            f"── poll check#{sample.check_index} · skip  "
            f"p={p:.2f} t={sample.elapsed_sec:.1f}s ──",
            flush=True,
        )
        return

    result = sample.result
    if result is None:
        return
    mark = "SPEAK" if result.spoke else result.rhythm.gate
    print(
        f"── poll check#{sample.check_index} · {mark}  "
        f"p={p:.2f} t={sample.elapsed_sec:.1f}s idle={result.idle_ms}ms ──",
        flush=True,
    )
    if (
        not skip_answer
        and result.spoke
        and result.turn is not None
        and result.turn.answer.strip()
    ):
        print(f"agent> {result.turn.answer.strip()}", flush=True)
    print(
        f"  rhythm  gate={result.rhythm.gate} "
        f"tempo={_clip(result.rhythm.tempo or '-', 40)}",
        flush=True,
    )
    print(
        f"  guide  {_clip(result.rhythm.reply_guide or result.rhythm.reason or '-', 72)}",
        flush=True,
    )
    print(f"  {_stage_line(result.stage)}", flush=True)


def print_poll_header(
    *,
    horizon_sec: float,
    check_sec: float,
    p_start: float,
    p_end: float,
    curve: str = "sqrt",
) -> None:
    print(flush=True)
    print(
        f"── rhythm poll · {curve} decay  "
        f"p {p_start:.2f}→{p_end:.2f} over {horizon_sec:.0f}s "
        f"(check={check_sec:.1f}s) ──",
        flush=True,
    )


def print_review(abstract: str, summary: str) -> None:
    print(flush=True)
    print("── rhythm review · 伪学习复盘 ──", flush=True)
    print(f"  abstract  {_clip(abstract or '-', 96)}", flush=True)
    body = " ".join((summary or "").split())
    if len(body) > 280:
        body = body[:279] + "…"
    print(f"  summary   {body or '-'}", flush=True)


def print_done() -> None:
    print(flush=True)
    print("[speak-demo] done", flush=True)
