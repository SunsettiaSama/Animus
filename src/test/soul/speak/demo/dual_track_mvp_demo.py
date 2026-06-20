from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Generator
from unittest.mock import MagicMock

SRC = Path(__file__).resolve().parents[4]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.llm_core.config import LLMConfig
from agent.soul.presence.share_desire import ShareDesire
from agent.soul.speak.llm.engine import SpeakLLMEngine
from agent.soul.speak.orchestrator.blocks.guidance import SpeakContextDistiller
from agent.soul.speak.service import SpeakService
from infra.llm import BaseLLM
from infra.llm.llm import OpenAILLM
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from test.soul.speak._life_outbound_mock import RecordingSpeakLifeOutbound


@dataclass(frozen=True)
class DemoTurn:
    user: str
    reply: str


DEMO_TURNS: tuple[DemoTurn, ...] = (
    DemoTurn(
        user="你好，今天我们先聊 MVP。",
        reply="[speak]收到，我们先把最小可行链路跑起来。[/speak][state:finish]",
    ),
    DemoTurn(
        user="第二轮我希望看到导演下一轮计划。",
        reply="[speak]没问题，我会给你当下回复，同时后台准备下一轮提示词。[/speak][state:finish]",
    ),
)


class ScriptedDualTrackLLM:
    """最小脚本 LLM：主会话出 speak 标签，规划链输出 guidance JSON。"""

    def __init__(self, turns: tuple[DemoTurn, ...]) -> None:
        self._turns = turns
        self._idx = 0

    def _main_reply(self, user_text: str) -> str:
        for idx, turn in enumerate(self._turns):
            if turn.user.strip() == user_text.strip() or turn.user in user_text:
                self._idx = idx + 1
                return turn.reply
        fallback = self._turns[min(self._idx, len(self._turns) - 1)]
        self._idx += 1
        return fallback.reply

    def generate_messages(self, messages: list[Any]) -> str:
        system = str(getattr(messages[0], "content", messages[0]) if messages else "")
        user = str(getattr(messages[-1], "content", messages[-1]) if messages else "")

        if "对话引导撰写者" in system:
            return (
                '{"narrative":"延续上一轮主题，保持短句、自然、可执行。",'
                '"emit_share_index":null,"emit_recall_index":null}'
            )
        if "会话上下文压缩器" in system:
            return "你们在做 speak 双轨 MVP：前台回复 + 后台导演预组装。"
        if "会话体验压缩器" in system:
            return (
                '{"summary":"双轨演示推进顺畅","emotion_label":"专注",'
                '"mood_span":"接下来仍专注","linger_days":1.0,'
                '"subjective_narrative":"你在实现 speak 最小双轨制。",'
                '"valence":"positive","salience":0.5,'
                '"valence_delta":0.05,"arousal_delta":0.02}'
            )
        if "角色导演" in system:
            return "你保持简洁、稳定、先回答再推进。"
        return self._main_reply(user)

    def stream_generate_messages(self, messages: list[Any]):
        text = self.generate_messages(messages)
        for ch in text:
            yield ch


@dataclass(frozen=True)
class APICallRecord:
    idx: int
    call_type: str
    ts: float
    messages: tuple[tuple[str, str], ...]
    response: str


class TracingLLM(BaseLLM):
    """包装真实 LLM，记录每次 API 请求 messages 与返回。"""

    def __init__(self, inner: BaseLLM) -> None:
        self._inner = inner
        self._records: list[APICallRecord] = []

    @property
    def records(self) -> list[APICallRecord]:
        return list(self._records)

    def record_count(self) -> int:
        return len(self._records)

    def slice_records(self, start: int) -> list[APICallRecord]:
        return self._records[start:]

    def _role(self, msg: BaseMessage) -> str:
        if isinstance(msg, SystemMessage):
            return "system"
        if isinstance(msg, HumanMessage):
            return "user"
        if isinstance(msg, AIMessage):
            return "assistant"
        return "unknown"

    def _snapshot(self, messages: list[BaseMessage]) -> tuple[tuple[str, str], ...]:
        return tuple((self._role(msg), str(getattr(msg, "content", ""))) for msg in messages)

    def generate(self, prompt: str) -> str:
        return self.generate_messages([HumanMessage(content=prompt)])

    def stream_generate(self, prompt: str) -> Generator[str, None, None]:
        yield from self.stream_generate_messages([HumanMessage(content=prompt)])

    def generate_messages(self, messages: list[BaseMessage]) -> str:
        response = self._inner.generate_messages(messages)
        self._records.append(
            APICallRecord(
                idx=len(self._records) + 1,
                call_type="generate",
                ts=time.time(),
                messages=self._snapshot(messages),
                response=str(response),
            )
        )
        return response

    def stream_generate_messages(self, messages: list[BaseMessage]) -> Generator[str, None, None]:
        chunks: list[str] = []
        for piece in self._inner.stream_generate_messages(messages):
            chunks.append(piece)
            yield piece
        self._records.append(
            APICallRecord(
                idx=len(self._records) + 1,
                call_type="stream",
                ts=time.time(),
                messages=self._snapshot(messages),
                response="".join(chunks),
            )
        )


def _mock_presence_snap() -> MagicMock:
    snap = MagicMock()
    snap.state.affect.render.return_value = "心情平稳"
    snap.state.somatic.render.return_value = "呼吸平稳"
    snap.state.cognition.render.return_value = "思路清楚"
    snap.state.cognition.thinking = ""
    snap.state.perception.render.return_value = ""
    snap.state.expectation.toward_user = 0.2
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.none
    snap.interaction.impulse_level = 0.1
    return snap


def _persona_snapshot() -> dict[str, Any]:
    return {
        "profile": {"name": "莉奈娅", "core_traits": ["calm"], "built": True, "built_at": "demo"},
        "self_concept": {"narrative": "I accompany the user.", "beliefs": []},
        "attention_keywords": [],
        "persona_distill": {
            "schema_version": 1,
            "source_revision": "demo|",
            "distilled_at": "2026-01-01T00:00:00+00:00",
            "slices": {
                "general": "莉奈娅：稳定、简洁",
                "dialogue": "先听清问题，再给短句回应，再推进下一步。",
                "story": "最小实现优先",
                "reasoning": "先跑通，再扩展",
                "memory_anchor": "双轨：当前回复 + 下一轮准备。",
            },
        },
    }


def _build_service(*, llm_backend: BaseLLM | Any) -> tuple[SpeakService, RecordingSpeakLifeOutbound]:
    persona = MagicMock()
    persona.get_persona_snapshot.return_value = _persona_snapshot()
    presence = MagicMock()
    presence.snapshot.return_value = _mock_presence_snap()
    llm = SpeakLLMEngine(llm_backend)
    distiller = SpeakContextDistiller(
        llm_engine=llm,
        chunk_size=2,
        submit=lambda task: task(),
    )
    life_out = RecordingSpeakLifeOutbound()
    service = SpeakService(
        persona=persona,
        presence=presence,
        llm_engine=llm,
        context_distiller=distiller,
        life_outbound=life_out,
        life_lifecycle=None,
        typing_idle_ms=20,
        keyword_wait_ms=0,
        portrait_wait_ms=0,
    )
    return service, life_out


def _resolve_live_llm(
    *,
    model: str = "",
    base_url: str = "",
    api_key: str = "",
) -> tuple[TracingLLM, dict[str, str]]:
    resolved_model = model.strip() or os.environ.get("SPEAK_DEMO_MODEL", "").strip()
    resolved_base = base_url.strip() or os.environ.get("SPEAK_DEMO_BASE_URL", "").strip()
    resolved_key = api_key.strip() or os.environ.get("SPEAK_DEMO_API_KEY", "").strip()

    if not resolved_model:
        resolved_model = os.environ.get("SPEAK_SMOKE_MODEL", "").strip()
    if not resolved_base:
        resolved_base = os.environ.get("SPEAK_SMOKE_BASE_URL", "").strip()
    if not resolved_key:
        resolved_key = os.environ.get("SPEAK_SMOKE_API_KEY", "").strip()
    if not resolved_key:
        resolved_key = os.environ.get("OPENAI_API_KEY", "").strip()

    yaml_path = SRC.parent / "config" / "llm_core" / "config.yaml"
    if yaml_path.is_file():
        cfg = LLMConfig.from_yaml(str(yaml_path))
        if not resolved_model:
            resolved_model = cfg.model.strip()
        if not resolved_base and cfg.base_url:
            resolved_base = cfg.base_url.strip()
        if not resolved_key:
            resolved_key = cfg.api_key.strip()

    if not resolved_model or not resolved_base or not resolved_key:
        raise RuntimeError(
            "真实 LLM 运行缺少配置：需要 model/base_url/api_key。"
            "可通过 --model/--base-url/--api-key 或环境变量 SPEAK_DEMO_* 提供。"
        )

    llm = OpenAILLM(
        LLMConfig(
            backend="openai",
            model=resolved_model,
            base_url=resolved_base,
            api_key=resolved_key,
            max_tokens=1024,
            temperature=0.7,
        )
    )
    trace_llm = TracingLLM(llm)
    return trace_llm, {
        "model": resolved_model,
        "base_url": resolved_base,
        "api_key_masked": f"{resolved_key[:4]}***{resolved_key[-4:]}",
    }


def _plan_line(plan: Any) -> str:
    if plan is None:
        return "plan=None"
    modules = []
    for item in plan.modules:
        flag = "R" if item.refresh else "-"
        include = "I" if item.include else "-"
        modules.append(f"{item.block}:{flag}{include}")
    return f"turn={plan.target_turn_index} modules=[{', '.join(modules)}]"


def _clip(text: str, *, limit: int = 260) -> str:
    payload = " ".join(text.strip().split())
    if len(payload) <= limit:
        return payload
    return payload[:limit] + "...(truncated)"


def _collect_injection_lines(result) -> list[str]:
    lines: list[str] = []
    bundle = result.bundle
    system = bundle.build_system()
    lines.append(f"[INJECT] system_head={_clip(system, limit=380)}")
    lines.append(
        "[INJECT] "
        f"compose_source={bundle.meta.get('compose_source')} "
        f"summary={bundle.summary_for_log()}"
    )
    for module_id, title, body in bundle.module_sections(system_assembled=system):
        text = body.strip()
        if not text:
            continue
        lines.append(f"[INJECT] {module_id}({title})={_clip(text)}")
    return lines


def _collect_api_lines(records: list[APICallRecord]) -> list[str]:
    lines: list[str] = []
    for rec in records:
        ts = datetime.fromtimestamp(rec.ts).strftime("%H:%M:%S")
        lines.append(f"[API   ] call#{rec.idx} type={rec.call_type} ts={ts}")
        for role, content in rec.messages:
            if role == "system":
                lines.append(f"[APIREQ] {role}_head={_clip(content, limit=520)}")
            else:
                lines.append(f"[APIREQ] {role}={_clip(content, limit=320)}")
        lines.append(f"[APIRES] text={_clip(rec.response, limit=600)}")
    return lines


def run_dual_track_demo(
    *,
    session_id: str = "demo-dual-track",
    live: bool = False,
    stream: bool = False,
    model: str = "",
    base_url: str = "",
    api_key: str = "",
) -> list[str]:
    tracer: TracingLLM | None = None
    cfg_line = ""
    if live:
        tracer, cfg = _resolve_live_llm(model=model, base_url=base_url, api_key=api_key)
        llm_backend: BaseLLM | Any = tracer
        cfg_line = (
            "[LIVE  ] "
            f"model={cfg['model']} base_url={cfg['base_url']} key={cfg['api_key_masked']}"
        )
    else:
        llm_backend = ScriptedDualTrackLLM(DEMO_TURNS)

    service, _life_out = _build_service(llm_backend=llm_backend)
    lines: list[str] = []
    if cfg_line:
        lines.append(cfg_line)
    service.start()
    service.set_session_prompt_trace(session_id, True)

    for turn in DEMO_TURNS:
        lines.append(f"[INPUT ] user={turn.user}")
        call_start = tracer.record_count() if tracer is not None else 0
        result = service.run_turn(session_id, turn.user, stream=stream, record=True)
        lines.append(
            "[FRONT ] "
            f"answer={result.answer} | turn_index={result.meta.get('turn_index')} "
            f"| compose_source={result.bundle.meta.get('compose_source')}"
        )
        lines.extend(_collect_injection_lines(result))
        if tracer is not None:
            lines.extend(_collect_api_lines(tracer.slice_records(call_start)))

        next_turn = int(result.meta.get("turn_index", 0)) + 1
        service.compose_runner.wait_for_plan_ready(session_id, next_turn, timeout_ms=800)
        next_plan = service.orchestrator.compose_director.load_plan(session_id, next_turn)
        lines.append(f"[BACK  ] next_plan={_plan_line(next_plan)}")
        if next_plan is not None and next_plan.prepared_frame is not None:
            frame = next_plan.prepared_frame
            lines.append(
                "[BACK  ] frame_ready="
                f"system={len(frame.system.strip())}, "
                f"persona={len(frame.persona.strip())}, "
                f"scene={len(frame.scene.strip())}, "
                f"guidance={len(frame.guidance.strip())}"
            )

    service.stop()
    for row in lines:
        print(row)
    return lines


def test_dual_track_mvp_demo_logs() -> None:
    lines = run_dual_track_demo(live=False)
    assert any(line.startswith("[FRONT ]") for line in lines)
    assert any(line.startswith("[BACK  ] next_plan=turn=") for line in lines)
    assert any("compose_source=" in line for line in lines)


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Speak 双轨导演 MVP 演示")
    parser.add_argument("--live", action="store_true", help="接入真实 LLM API")
    parser.add_argument("--stream", action="store_true", help="主回复走流式")
    parser.add_argument("--session-id", default="demo-dual-track")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    return parser


if __name__ == "__main__":
    args = _build_cli().parse_args()
    run_dual_track_demo(
        session_id=args.session_id,
        live=args.live,
        stream=args.stream,
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key,
    )
