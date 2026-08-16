#!/usr/bin/env python3
"""十轮贴近真实 speak 场景的模拟：

  模拟编剧 SimScreenwriter
    - 维护 plot_arc 剧情 unit 队列（章节迭代，不会永远撬锁）
    - 队列耗尽或章节收束时 replace_from_payload 写下一章

  模拟导演 SimDirector
    - seed_plot_unit_consumption_queue 预编排可执行开口
    - poll：到期则挂 origin=director handoff（主动抛出）
    - 用户入站：bind_delivery_step_for_user（保留后续剧情队列）

  角色 Character
    - 真实 system prompt + DeepSeek 生成 body/speak
    - 交付成功 → mark_consumed + advance_plot_queue_on_delivery

十轮脚本：用户打断与导演主动穿插，对应真实 user / director 双 origin。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


Origin = Literal["user", "director"]


# ---------------------------------------------------------------------------
# 剧情章节：编剧用；每章 2～3 个 InteractionUnit，做完就换章，不再死磕锁扣
# ---------------------------------------------------------------------------

PLOT_CHAPTERS: tuple[dict[str, Any], ...] = (
    {
        "id": "ch0_lock",
        "summary": "晨光标本台：旋开金属锁扣，保护蜡膜与针尖对齐。",
        "evidence": "书签、横纹、蜡膜、第十八格针尖、露米警戒",
        "units": (
            "用书签边缘抵住锁扣槽口，找准横纹末端",
            "沿横纹方向缓旋，分辨阻力是卡死还是可松",
            "阻力松动后旋开，立刻确认蜡膜未裂、针尖仍对齐",
        ),
        "focus": "旋锁扣",
        "mood": "专注，略紧",
        "brief": "锁扣差一点就能开，时间紧。",
    },
    {
        "id": "ch1_case",
        "summary": "锁扣已开：揭开盒盖，核对标本与焦褐粉末。",
        "evidence": "盒盖铰链、半枚爪印拓片、焦褐粉末、露米耳尖",
        "units": (
            "双手稳住盒盖，沿铰链缓缓揭开一掌宽",
            "借晨光看清盒内拓片边缘与粉末落点",
            "把半枚爪印角度与先前记录在心里对上号",
        ),
        "focus": "揭盒看标本",
        "mood": "好奇压过紧张",
        "brief": "锁开了，真正要看的东西露出来了。",
    },
    {
        "id": "ch2_note",
        "summary": "记录发现：在本子上落一两笔，顺口跟远方熟人说清要点。",
        "evidence": "笔记本、炭笔、拓片分叉角、帐外营地动静",
        "units": (
            "在本子边角记下分叉角与粉末色泽",
            "把「这不是普通爪印」压成一句可发的短讯念头",
        ),
        "focus": "记笔记并整理说法",
        "mood": "松一点，仍在想",
        "brief": "东西看清了，该落笔、也该回话。",
    },
    {
        "id": "ch3_wrap",
        "summary": "收束：合盖、归拢工具，准备应付帐外往来。",
        "evidence": "盒盖、书签、针盒、帐帘、露米",
        "units": (
            "合上盒盖但不重锁，书签夹回原页",
            "抬头看一眼帐帘外，确认露米仍在警戒位",
        ),
        "focus": "收拢收尾",
        "mood": "松弛下来",
        "brief": "这拍告一段落，可以更自然地跟人说话。",
    },
)


# 十轮时间线：贴近真实 —— 用户直入 + 导演主动手递
TEN_BEATS: tuple[dict[str, Any], ...] = (
    {
        "origin": "director",
        "cue": "按台本推进本拍：先动手，再决定要不要发一句。",
        "label": "导演主动·开场动手",
    },
    {
        "origin": "user",
        "text": "喂，到营地外围了。帐篷里还好吗？你在干嘛呢？",
        "label": "用户打断·寒暄",
    },
    {
        "origin": "director",
        "cue": "继续当前剧情步骤，可短抛一句近况，勿复述已说过的点。",
        "label": "导演主动·推进锁扣",
    },
    {
        "origin": "user",
        "text": "别拧了，听我的——拿刀直接撬开不更快？",
        "label": "用户·错误建议",
    },
    {
        "origin": "director",
        "cue": "若锁扣已处理完，自然过渡到下一步；否则把本拍做完。",
        "label": "导演主动·收束/过渡",
    },
    {
        "origin": "user",
        "text": "盒里到底是什么？给我说说你看到了啥。",
        "label": "用户·追问发现",
    },
    {
        "origin": "director",
        "cue": "主动抛出你刚确认的一点观察，短句，像发消息不是报告。",
        "label": "导演主动·分享观察",
    },
    {
        "origin": "user",
        "text": "晚上火锅还是烧烤？快点选一个嘛～",
        "label": "用户·不合时宜闲聊",
    },
    {
        "origin": "director",
        "cue": "收尾拍：合盖或归拢工具时，可主动丢一句收束。",
        "label": "导演主动·收尾",
    },
    {
        "origin": "user",
        "text": "那我先去河边一趟，有事你喊我。",
        "label": "用户·暂别",
    },
)


def _sep(title: str) -> None:
    print(f"\n{'=' * 72}\n  {title}\n{'=' * 72}", flush=True)


def _load_engine(args: argparse.Namespace):
    from config.llm_core.config import LLMConfig
    from infra.llm.llm import OpenAILLM
    from agent.soul.speak.llm.engine import SpeakLLMEngine

    cfg_path = ROOT / "config" / "llm_core" / "config.yaml"
    cfg = LLMConfig.from_yaml(str(cfg_path)) if cfg_path.is_file() else LLMConfig()
    api_key = (
        args.api_key
        or os.environ.get("SPEAK_SMOKE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or cfg.api_key
        or ""
    ).strip()
    model = (args.model or os.environ.get("SPEAK_SMOKE_MODEL") or cfg.model or "").strip()
    base_url = (
        args.base_url
        or os.environ.get("SPEAK_SMOKE_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or cfg.base_url
        or ""
    ).strip()
    if not api_key or not model:
        raise SystemExit("missing api_key/model")
    print(f"model={model}  base_url={base_url or '(default)'}")
    return SpeakLLMEngine(
        OpenAILLM(
            LLMConfig(
                backend="openai",
                model=model,
                api_key=api_key,
                base_url=base_url or None,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
            )
        )
    )


# ---------------------------------------------------------------------------
# 模拟编剧
# ---------------------------------------------------------------------------


class SimScreenwriter:
    """模拟编剧：只写剧情议程与场记，不写角色台词。"""

    def __init__(self, chapters: tuple[dict[str, Any], ...] = PLOT_CHAPTERS) -> None:
        self.chapters = chapters
        self.chapter_index = 0
        self.history: list[str] = []

    @property
    def chapter(self) -> dict[str, Any]:
        return self.chapters[min(self.chapter_index, len(self.chapters) - 1)]

    def init_presence(self, state: Any) -> str:
        """对应 Screenwriter.init_presence：写入首章 plot_arc + presence。"""
        note = self._apply_chapter(state, self.chapters[0], reason="init_presence")
        self.chapter_index = 0
        self.history.append(note)
        return note

    def maybe_iterate(
        self,
        state: Any,
        *,
        force: bool = False,
        reason: str = "",
    ) -> str | None:
        """队列耗尽或强制收束时，迭代到下一章（对应编剧 replace_arc）。"""
        arc = state.plot_arc
        exhausted = (
            arc is None
            or not getattr(arc, "ready", False)
            or arc.active_unit() is None
            or all(u.status == "done" for u in arc.units)
        )
        if not force and not exhausted:
            return None
        nxt = self.chapter_index + 1
        if nxt >= len(self.chapters):
            self.history.append("screenwriter:keep_final_chapter")
            return None
        self.chapter_index = nxt
        note = self._apply_chapter(
            state,
            self.chapters[nxt],
            reason=reason or "arc_exhausted_iterate",
        )
        self.history.append(note)
        return note

    def _apply_chapter(self, state: Any, chapter: dict[str, Any], *, reason: str) -> str:
        from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
            PlotArc,
        )

        payload = {
            "summary": chapter["summary"],
            "evidence": chapter["evidence"],
            "units": [{"intent": intent, "evidence": chapter["evidence"]} for intent in chapter["units"]],
        }
        prev = state.plot_arc if getattr(state.plot_arc, "ready", False) else PlotArc()
        state.plot_arc = prev.replace_from_payload(payload)
        state.presence_card.mood = chapter["mood"]
        state.presence_card.brief = chapter["brief"]
        state.presence_card.speak_desire = 45 if self.chapter_index < 2 else 62
        state.presence_card.fate_tendency = (
            "克制开口" if self.chapter_index < 2 else "可主动抛一句"
        )
        state.director_cache["plot_arc"] = state.plot_arc.snapshot()
        state.director_cache["screenwriter_chapter"] = chapter["id"]
        return f"screenwriter:advance chapter={chapter['id']} reason={reason}"


# ---------------------------------------------------------------------------
# 模拟导演
# ---------------------------------------------------------------------------


class SimDirector:
    """模拟导演：只排可执行 unit / handoff，不写台词。"""

    def __init__(self) -> None:
        self.history: list[str] = []

    def seed_queue(self, state: Any, *, now: float | None = None) -> str:
        from agent.soul.speak.responders.request_driven.directors.rhythm_schedule import (
            seed_plot_unit_consumption_queue,
        )
        from agent.soul.speak.responders.request_driven.orchestrator.state.core.character_rhythm_schedule import (
            CharacterRhythmSchedule,
        )

        # 清空旧 pending，允许按新章重编
        kept = [
            e
            for e in state.character_rhythm_schedule.executable_units
            if e.status in ("consumed", "cancelled", "fired")
        ]
        base = CharacterRhythmSchedule(
            executable_units=kept,
            consumption_history=list(
                state.character_rhythm_schedule.consumption_history
            ),
            version=int(state.character_rhythm_schedule.version or 1),
        )
        state.character_rhythm_schedule = seed_plot_unit_consumption_queue(
            base,
            now=now if now is not None else time.time(),
            plot_arc=state.plot_arc,
        )
        # 模拟「到点」：把当前 active 绑定的那条立刻到期，便于本拍主动抛出
        active = state.plot_arc.active_unit()
        if active is not None:
            aid = active.unit_id
            for entry in state.character_rhythm_schedule.executable_units:
                if entry.status == "pending" and aid in entry.plot_unit_ids:
                    entry.open_at = time.time()
                    break
        state.director_cache["character_rhythm_schedule"] = (
            state.character_rhythm_schedule.snapshot()
        )
        note = (
            "director:seed_plot_queue "
            f"pending={sum(1 for e in state.character_rhythm_schedule.executable_units if e.status == 'pending')}"
        )
        self.history.append(note)
        return note

    def take_proactive_handoff(self, state: Any, *, turn_index: int, cue: str) -> dict[str, Any] | None:
        """对应 _mark_schedule_speak_handoff → pending_character_handoff。"""
        from agent.soul.speak.responders.request_driven.character.contracts import (
            CharacterReplyRequest,
            DeliveryIntent,
        )
        from agent.soul.speak.responders.request_driven.character.context import (
            build_narrative_snapshot,
        )

        rhythm = state.character_rhythm_schedule
        due = rhythm.due_units(now=time.time())
        if not due:
            pending = [e for e in rhythm.executable_units if e.status == "pending"]
            if not pending:
                self.history.append("director:no_pending_for_proactive")
                return None
            entry = min(pending, key=lambda e: float(e.open_at))
            entry.open_at = time.time()
        else:
            entry = min(due, key=lambda e: float(e.open_at))

        rhythm.mark_reserved(entry.unit_id)
        narrative = build_narrative_snapshot(state, origin="director", user_text="")
        request = CharacterReplyRequest(
            origin="director",
            session_id=state.session_id,
            turn_index=turn_index,
            trigger_id=f"director:{entry.unit_id}:{turn_index}",
            director_cue=cue,
            reason="sim_director_proactive",
            narrative=narrative,
            delivery_intent=DeliveryIntent(
                speak_gate="speak",
                continuity="finish",
                plan_id=f"schedule-{entry.unit_id}",
            ),
            executable_unit_id=entry.unit_id,
            plot_unit_ids=tuple(entry.plot_unit_ids),
        )
        state.pending_character_handoff = request.to_dict()
        note = f"director:handoff exec={entry.unit_id} plot={','.join(entry.plot_unit_ids)}"
        self.history.append(note)
        return request.to_dict()

    def bind_user_turn(self, state: Any, *, turn_index: int, user_text: str) -> tuple[str, tuple[str, ...]]:
        from agent.soul.speak.responders.request_driven.character.context import (
            bind_delivery_step_for_user,
        )

        # 用户入站撤销主动 handoff（真实 coordinator fast 路径）
        state.pending_character_handoff = None
        step_id, plot_ids, _ = bind_delivery_step_for_user(
            state,
            session_id=state.session_id,
            turn_index=turn_index,
        )
        self.history.append(
            f"director:user_bind exec={step_id} plot={','.join(plot_ids) or '—'}"
        )
        return step_id, plot_ids


# ---------------------------------------------------------------------------
# 会话状态 / 角色生成
# ---------------------------------------------------------------------------


def _new_state(session_id: str) -> Any:
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.character_rhythm_schedule import (
        CharacterRhythmSchedule,
    )
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
        PlotArc,
    )

    return SimpleNamespace(
        session_id=session_id,
        plot_arc=PlotArc(),
        plot_flow=None,
        character_rhythm_schedule=CharacterRhythmSchedule(),
        director_cache={},
        pending_character_handoff=None,
        poll_seq=0,
        notes=[],
        agent_speak_count=0,
        narrative_card=SimpleNamespace(
            interaction_mode="",
            user_activity="",
            user_identity="营地外的熟人",
            scene_event="",
            ready=True,
        ),
        presence_card=SimpleNamespace(
            ready=True,
            mood="",
            brief="",
            speak_desire=40,
            fate_tendency="",
            render=lambda self=None: "",
        ),
        silence_log=SimpleNamespace(ready=False, render=lambda: ""),
    )


def _base_system(*, origin: Origin) -> str:
    from agent.soul.speak.responders.request_driven.orchestrator.blocks.system.role import (
        build_role,
    )

    persona = (
        "【身份】你是莉奈娅（Linnea），妖精族换生灵、博物向观察者。"
        "说话短句、带自然比喻；动手时注意力常还在物件上。"
        "露米是你的警戒伙伴，蹲在帐帘旁。"
    )
    mode = "proactive" if origin == "director" else "inbound"
    return f"{build_role(mode)}\n\n{persona}"


def _generate_character(
    engine,
    state: Any,
    *,
    origin: Origin,
    user_text: str,
    director_cue: str,
    base: str,
) -> str:
    from agent.soul.speak.responders.request_driven.character.context import (
        build_narrative_snapshot,
    )
    from agent.soul.speak.responders.request_driven.composer.projectors.dynamic_layer import (
        DynamicLayerMaterials,
        DynamicLayerSchedule,
    )
    from agent.soul.speak.responders.request_driven.composer.projectors.role_view import (
        RoleContextView,
    )
    from agent.soul.speak.responders.request_driven.prompt import build_role_prompt

    narrative = build_narrative_snapshot(
        state,
        origin=origin,
        user_text=user_text if origin == "user" else "",
    )
    active = state.plot_arc.active_unit() if state.plot_arc.ready else None
    flow = f"此刻步骤：{active.intent}" if active is not None else "当前无进行中的剧情步骤"
    chapter = state.director_cache.get("screenwriter_chapter", "")
    prompt = build_role_prompt(
        RoleContextView(session_id=state.session_id),
        user_text=user_text if origin == "user" else director_cue,
        materials=DynamicLayerMaterials(session_id=state.session_id),
        schedule=DynamicLayerSchedule(reason=f"ten_turn:{origin}"),
        interaction_channel=narrative.interaction_channel,
        plot_outline_text=narrative.plot_outline_text,
        plot_flow_text=f"{flow}\n章节={chapter}",
        presence_mood=narrative.presence_mood or state.presence_card.mood,
        presence_brief=narrative.presence_brief or state.presence_card.brief,
        presence_speak_desire=narrative.presence_speak_desire
        if narrative.presence_speak_desire is not None
        else state.presence_card.speak_desire,
        presence_fate_tendency=narrative.presence_fate_tendency
        or state.presence_card.fate_tendency,
        user_identity=narrative.user_identity,
        user_activity=narrative.user_activity,
    )
    system = f"{base}\n\n{prompt.system_extra}".strip()
    ingress = user_text if origin == "user" else (director_cue or "（继续你手头的事）")
    return engine.generate(ingress, system=system).text


def _commit_delivery(
    state: Any,
    *,
    step_id: str,
    plot_ids: tuple[str, ...],
    turn_index: int,
    origin: Origin,
    raw: str,
    screenwriter: SimScreenwriter,
    director: SimDirector,
) -> str:
    from agent.soul.speak.responders.request_driven.character.consume import (
        advance_plot_queue_on_delivery,
    )
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.character_rhythm_schedule import (
        plot_progress_fingerprint,
    )

    if not str(raw or "").strip():
        state.character_rhythm_schedule.release_reserved(step_id)
        return "silence:release_reserved"

    fp = plot_progress_fingerprint(state.plot_arc, state.plot_flow)
    script = ""
    for entry in state.character_rhythm_schedule.executable_units:
        if entry.unit_id == step_id:
            script = str(entry.script_text or "")
            break
    state.character_rhythm_schedule.mark_consumed(
        step_id,
        turn_index=turn_index,
        trigger_id=f"{origin}:{step_id}:{turn_index}",
        plot_fingerprint=fp,
        script_text=script,
        answer_fingerprint=raw[:120],
    )
    next_intent = advance_plot_queue_on_delivery(
        state,
        plot_unit_ids=plot_ids,
        reason=f"ten_turn:{origin}:{turn_index}",
    )
    state.agent_speak_count = int(state.agent_speak_count or 0) + 1
    notes = [f"commit next={next_intent or '∅'}"]

    # 队列耗尽 → 编剧迭代下一章 → 导演重编消费队列
    iterated = screenwriter.maybe_iterate(state)
    if iterated:
        notes.append(iterated)
        notes.append(director.seed_queue(state))
    return " | ".join(notes)


def _print_queue(state: Any, screenwriter: SimScreenwriter, label: str) -> None:
    arc = state.plot_arc
    rhythm = state.character_rhythm_schedule
    ch = screenwriter.chapter
    print(f"\n[{label}] chapter={ch['id']}  speak_count={state.agent_speak_count}")
    active = arc.active_unit() if arc.ready else None
    print(f"  active={active.intent if active else '∅'}")
    for i, u in enumerate(arc.units):
        mark = {"active": "*", "pending": ".", "done": "x"}.get(u.status, "?")
        print(f"  {mark} [{i}] {u.status:8} {u.intent}")
    pending = sum(1 for e in rhythm.executable_units if e.status == "pending")
    consumed = sum(1 for e in rhythm.executable_units if e.status == "consumed")
    print(f"  exec pending={pending} consumed={consumed}")


@dataclass
class TurnRecord:
    index: int
    origin: Origin
    label: str
    ingress: str
    raw: str
    commit: str
    chapter: str


@dataclass
class SceneRun:
    records: list[TurnRecord] = field(default_factory=list)


def run_scene(engine, *, max_turns: int = 10) -> SceneRun:
    state = _new_state("ten-turn-scene")
    screenwriter = SimScreenwriter()
    director = SimDirector()
    scene = SceneRun()

    _sep("1) 编剧 init_presence → 导演 seed 消费队列")
    print(screenwriter.init_presence(state))
    print(director.seed_queue(state))
    _print_queue(state, screenwriter, "seed")

    beats = TEN_BEATS[: max(1, int(max_turns))]
    for i, beat in enumerate(beats, start=1):
        origin: Origin = beat["origin"]
        label = beat["label"]
        base = _base_system(origin=origin)
        _sep(f"Turn {i}/{len(beats)}  [{origin}] {label}")

        if origin == "user":
            user_text = str(beat["text"])
            cue = ""
            print(f"USER: {user_text}")
            step_id, plot_ids = director.bind_user_turn(
                state, turn_index=i, user_text=user_text
            )
            ingress = user_text
        else:
            user_text = ""
            cue = str(beat["cue"])
            print(f"DIRECTOR_CUE: {cue}")
            handoff = director.take_proactive_handoff(
                state, turn_index=i, cue=cue
            )
            if handoff is None:
                # 无 pending：强制编剧迭代后再 seed
                note = screenwriter.maybe_iterate(state, force=True, reason="proactive_starved")
                if note:
                    print(note)
                director.seed_queue(state)
                handoff = director.take_proactive_handoff(
                    state, turn_index=i, cue=cue
                )
            if handoff is None:
                print("SKIP: no handoff available")
                continue
            step_id = str(handoff.get("executable_unit_id") or "")
            plot_ids = tuple(handoff.get("plot_unit_ids") or ())
            ingress = cue

        active = state.plot_arc.active_unit() if state.plot_arc.ready else None
        print(f"ACTIVE_BEFORE: {active.intent if active else '∅'}")
        print(f"BOUND: exec={step_id} plot={plot_ids}")

        raw = _generate_character(
            engine,
            state,
            origin=origin,
            user_text=user_text,
            director_cue=cue,
            base=base,
        )
        print(f"\n--- character raw ---\n{raw}")

        commit = _commit_delivery(
            state,
            step_id=step_id,
            plot_ids=plot_ids,
            turn_index=i,
            origin=origin,
            raw=raw,
            screenwriter=screenwriter,
            director=director,
        )
        print(f"\nCOMMIT: {commit}")
        _print_queue(state, screenwriter, f"after_turn_{i}")

        scene.records.append(
            TurnRecord(
                index=i,
                origin=origin,
                label=label,
                ingress=ingress,
                raw=raw,
                commit=commit,
                chapter=str(state.director_cache.get("screenwriter_chapter") or ""),
            )
        )

    _sep("summary")
    print("screenwriter history:")
    for line in screenwriter.history:
        print(f"  - {line}")
    print("director history:")
    for line in director.history:
        print(f"  - {line}")
    print("\nturns:")
    for rec in scene.records:
        speak = ""
        low = rec.raw.lower()
        if "<speak>" in low:
            start = rec.raw.lower().find("<speak>") + len("<speak>")
            end = rec.raw.lower().find("</speak>")
            if end > start:
                speak = rec.raw[start:end].strip().replace("\n", " ")
        print(
            f"  #{rec.index:02d} [{rec.origin:8}] ch={rec.chapter:12} "
            f"| {speak[:60] or '(no speak)'}"
        )
    return scene


def main() -> int:
    parser = argparse.ArgumentParser(description="Ten-turn screenwriter+director scene smoke")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--turns", type=int, default=10)
    args = parser.parse_args()

    _sep("load LLM")
    engine = _load_engine(args)
    run_scene(engine, max_turns=args.turns)
    _sep("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
