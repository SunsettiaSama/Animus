from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

from demos.speak.directors.reply import ReplyStreamer, TypePace
from demos.speak.io import SpeakOutbound
from demos.speak.runtime import Clock, DeliveryExecutor, FakeClock, RhythmPoller, SpeakDemoRunner
from demos.speak.shell import (
    DEFAULT_SCRIPT,
    EPOCH_PROACTIVE_SCRIPTS,
    EPOCH_SHARE_EVENTS,
    EPOCH_SCRIPTS,
    PROACTIVE_SCRIPT,
    AgentLineSink,
    ScriptedReplyGenerator,
    SoftChannelFixture,
    print_arc,
    print_banner,
    print_done,
    print_poll_header,
    print_poll_sample,
    print_review,
    print_turn_meta,
    seed_demo_stage,
)
from demos.speak.stage.review import RhythmReview


def _build_runner(
    args: argparse.Namespace,
    *,
    script=DEFAULT_SCRIPT,
    proactive_script=PROACTIVE_SCRIPT,
    share_events=None,
    session_id: str | None = None,
    prior_review: RhythmReview | None = None,
) -> tuple[SpeakDemoRunner, AgentLineSink]:
    stage = seed_demo_stage(
        session_id=session_id or args.session_id,
        share_events=share_events or EPOCH_SHARE_EVENTS[0],
        load_cached_review=args.load_review,
    )
    if prior_review is not None:
        stage.set_rhythm_review(prior_review)
    line_sink = AgentLineSink(show_think=args.show_think)
    streamer = ReplyStreamer(
        mode=args.stream_mode,
        pace=TypePace(scale=args.type_scale, seed=args.type_seed),
        sink=line_sink,
    )
    delivery = DeliveryExecutor(
        sleep=args.sleep,
        quiet=not args.verbose_delivery,
        streamer=streamer,
    )
    clock: Clock = FakeClock() if args.fast_poll else Clock()

    if args.mode == "offline":
        soft = SoftChannelFixture()
        reply_llm = ScriptedReplyGenerator(script, proactive_lines=proactive_script)
        runner = SpeakDemoRunner(
            stage,
            clock=clock,
            rhythm_llm=soft,
            reply_llm=reply_llm,
            init_llm=soft,
            delivery=delivery,
            on_scene_every_k=args.on_scene_k,
            affect_every_k=args.affect_k,
        )
        SpeakOutbound(streamer=streamer, delivery=delivery).bind_streamer(streamer)
        runner.reply.streamer = streamer
        runner.bind_script({t.user: t.reply for t in script})
        runner.bind_proactive_script(proactive_script)
        return runner, line_sink

    from demos.speak.io.llm_adapter import load_openai_adapter

    adapter = load_openai_adapter(args.llm_config)
    runner = SpeakDemoRunner(
        stage,
        clock=clock,
        rhythm_llm=adapter,
        reply_llm=adapter,
        init_llm=adapter,
        delivery=delivery,
        on_scene_every_k=args.on_scene_k,
        affect_every_k=args.affect_k,
    )
    SpeakOutbound(streamer=streamer, delivery=delivery).bind_streamer(streamer)
    runner.reply.streamer = streamer
    return runner, line_sink


def _run_script_turns(runner: SpeakDemoRunner, line_sink: AgentLineSink, script) -> None:
    for turn in script:
        line_sink.reset()
        print(flush=True)
        print(f"── user · turn {runner.stage.turn_index + 1} ──", flush=True)
        print(f"you> {turn.user}", flush=True)
        result = runner.run_turn(turn.user, deliver=True)
        if not line_sink.streamed:
            print(f"agent> {result.answer.strip() or '（未开口）'}", flush=True)
        print_turn_meta(result)
        line_sink.reset()


def _run_poll(args: argparse.Namespace, runner: SpeakDemoRunner, line_sink: AgentLineSink) -> None:
    print_poll_header(
        horizon_sec=args.poll_horizon,
        check_sec=args.poll_check,
        p_start=args.poll_p_start,
        p_end=args.poll_p_end,
        curve=args.poll_curve,
    )

    def _on_sample(sample) -> None:
        print_poll_sample(sample, skip_answer=line_sink.streamed)
        line_sink.reset()

    poller = RhythmPoller(
        runner,
        horizon_sec=args.poll_horizon,
        check_interval_sec=args.poll_check,
        p_start=args.poll_p_start,
        p_end=args.poll_p_end,
        max_checks=args.poll_max_checks,
        seed=args.poll_seed,
        curve=args.poll_curve,
        clock=runner.clock,
        on_sample=_on_sample,
    )
    poller.run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Speak 三导演小样（对话弧 + 衰减概率轮询）")
    parser.add_argument("--mode", choices=("offline", "llm"), default="offline")
    parser.add_argument(
        "--llm-config",
        default=str(ROOT / "config" / "llm_core" / "config.yaml"),
    )
    parser.add_argument("--session-id", default="demo-speak")
    parser.add_argument(
        "--load-review",
        action="store_true",
        help="显式载入同 session 的历史复盘；默认关闭，避免旧个例污染主链路",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=1,
        help="连续跑几场错开的脚本；上一场 review 只作为下一场原则参考",
    )
    parser.add_argument("--sleep", action="store_true")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--live", action="store_true", help="脚本后启动衰减概率轮询（快进时钟）")
    parser.add_argument("--poll", action="store_true", help="启用衰减概率轮询")
    parser.add_argument(
        "--poll-curve",
        choices=("sqrt", "linear"),
        default="sqrt",
        help="轮询衰减曲线：根号（默认）/ 线性旁路",
    )
    parser.add_argument("--poll-horizon", type=float, default=16.0, help="衰减地平线（秒），到达后停止")
    parser.add_argument("--poll-check", type=float, default=1.0, help="掷骰节拍（秒）")
    parser.add_argument("--poll-p-start", type=float, default=0.9, help="起始轮询概率")
    parser.add_argument("--poll-p-end", type=float, default=0.0, help="地平线处概率")
    parser.add_argument("--poll-max-checks", type=int, default=0, help="安全上限（0=不限，靠地平线停）")
    parser.add_argument("--poll-seed", type=int, default=None, help="掷骰随机种子")
    parser.add_argument(
        "--on-scene-k",
        type=int,
        default=3,
        help="rhythm 每隔 k 拍单独轮询临场状态（默认 3）",
    )
    parser.add_argument(
        "--affect-k",
        type=int,
        default=2,
        help="rhythm 每隔 k 拍修正情感底色（默认 2）",
    )
    parser.add_argument("--fast-poll", action="store_true", help="FakeClock 快进空闲")
    parser.add_argument(
        "--stream-mode",
        choices=("typewriter", "immediate", "immediate_stream"),
        default="immediate",
        help="回复推送：打字机 / 立刻整段 / 立刻分词流式",
    )
    parser.add_argument(
        "--type-scale",
        type=float,
        default=80.0,
        help="打字机 RMS scale（默认80≈20字/1.6s；70更快，90稍稳）",
    )
    parser.add_argument("--type-seed", type=int, default=None, help="打字机随机种子")
    parser.add_argument("--show-think", action="store_true", help="控制台打印 think 文本")
    parser.add_argument(
        "--verbose-delivery",
        action="store_true",
        help="打印旧版 [typing]/[speak] 交付明细",
    )
    args = parser.parse_args(argv)

    if args.live:
        args.poll = True
        args.fast_poll = True
        # 复杂样例多轮后测主动性/展开：拉长衰减地平线
        if args.poll_horizon == 16.0:
            args.poll_horizon = 28.0
        if args.poll_p_start == 0.9:
            args.poll_p_start = 0.95

    if args.interactive:
        runner, line_sink = _build_runner(args)
        print_banner(
            args.mode,
            args.session_id,
            share_n=len(runner.stage.share_queue),
            affect_label=runner.stage.affect.label,
        )
        prior = runner.stage.rhythm_review
        if prior is not None and prior.ready:
            print_review(prior.abstract, prior.summary)
        arc = runner.init_directors()
        print_arc(arc.source, arc.text)
        print("输入内容回车发送；空行结束用户输入。", flush=True)
        while True:
            user_text = input("you> ").strip()
            if not user_text:
                break
            line_sink.reset()
            print(flush=True)
            print(f"── user · turn {runner.stage.turn_index + 1} ──", flush=True)
            result = runner.run_turn(user_text, deliver=True)
            if not line_sink.streamed:
                print(f"agent> {result.answer.strip() or '（未开口）'}", flush=True)
            print_turn_meta(result)
            line_sink.reset()
        review = runner.review_session(persist=True)
        print_review(review.abstract, review.summary)
    else:
        prior_review: RhythmReview | None = None
        epoch_count = max(1, args.epochs)
        for epoch_idx in range(epoch_count):
            script = EPOCH_SCRIPTS[epoch_idx % len(EPOCH_SCRIPTS)]
            proactive_script = EPOCH_PROACTIVE_SCRIPTS[
                epoch_idx % len(EPOCH_PROACTIVE_SCRIPTS)
            ]
            share_events = EPOCH_SHARE_EVENTS[epoch_idx % len(EPOCH_SHARE_EVENTS)]
            session_id = args.session_id
            if epoch_count > 1:
                session_id = f"{args.session_id}-epoch-{epoch_idx + 1}"
            runner, line_sink = _build_runner(
                args,
                script=script,
                proactive_script=proactive_script,
                share_events=share_events,
                session_id=session_id,
                prior_review=prior_review,
            )
            print(flush=True)
            print(f"== epoch {epoch_idx + 1}/{epoch_count} · session={session_id} ==", flush=True)
            print_banner(
                args.mode,
                session_id,
                share_n=len(runner.stage.share_queue),
                affect_label=runner.stage.affect.label,
            )
            prior = runner.stage.rhythm_review
            if prior is not None and prior.ready:
                print_review(prior.abstract, prior.summary)
            arc = runner.init_directors()
            print_arc(arc.source, arc.text)
            _run_script_turns(runner, line_sink, script)
            if args.poll:
                _run_poll(args, runner, line_sink)
            prior_review = runner.review_session(persist=True)
            print_review(prior_review.abstract, prior_review.summary)
    print_done()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
