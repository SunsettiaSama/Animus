from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any

from .bundle import SpeakPromptBundle
from .trace import build_module_sections
from ..io.outbound.stream import SpeakAgentOutput


def _env_trace_enabled() -> bool:
    raw = os.environ.get("REACT_SPEAK_PROMPT_TRACE", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


@dataclass
class SpeakPromptTrace:
    """按 session 开关：在主进程 stdout 打印 compose 提示词与本地缓存快照。"""

    global_enabled: bool = field(default_factory=_env_trace_enabled)
    _sessions: set[str] = field(default_factory=set)

    def set_session(self, session_id: str, enabled: bool) -> None:
        sid = session_id.strip()
        if not sid:
            return
        if enabled:
            self._sessions.add(sid)
        else:
            self._sessions.discard(sid)

    def set_global(self, enabled: bool) -> None:
        self.global_enabled = enabled

    def is_enabled(self, session_id: str) -> bool:
        if self.global_enabled:
            return True
        return session_id.strip() in self._sessions

    def enabled_sessions(self) -> list[str]:
        return sorted(self._sessions)

    def emit_compose(
        self,
        session_id: str,
        *,
        turn_index: int,
        bundle: SpeakPromptBundle,
        cache: dict[str, Any],
        round_idx: int = 0,
        system_override: str | None = None,
    ) -> None:
        if not self.is_enabled(session_id):
            return
        system = system_override if system_override is not None else bundle.build_system()
        lines = [
            "",
            "=" * 72,
            f"[SPEAK TRACE] compose  session={session_id} turn={turn_index} round={round_idx}",
            "-" * 72,
            f"mode={bundle.mode} summary={bundle.summary_for_log()}",
            "-" * 72,
            "【本地缓存 · distiller / queues】",
            _format_cache(cache),
        ]
        for module_id, title, body in build_module_sections(
            bundle,
            system_assembled=system,
        ):
            lines.append("-" * 72)
            lines.append(f"【{title}】 id={module_id} · {len(body)} chars")
            lines.append(body if body else "(空)")
        lines.extend(["=" * 72, ""])
        _print_block(lines)

    def emit_submodule_llm(
        self,
        session_id: str,
        *,
        submodule: str,
        system: str,
        user: str,
        response_preview: str = "",
    ) -> None:
        if not self.is_enabled(session_id):
            return
        lines = [
            "",
            "=" * 72,
            f"[SPEAK TRACE] submodule={submodule} session={session_id}",
            "-" * 72,
            f"【system · {len(system)} chars】",
            system,
            "-" * 72,
            f"【user · {len(user)} chars】",
            user,
        ]
        if response_preview.strip():
            lines.append("-" * 72)
            lines.append(f"【response · {len(response_preview)} chars】")
            lines.append(response_preview.strip())
        lines.extend(["=" * 72, ""])
        _print_block(lines)

    def emit_turn_finish(
        self,
        session_id: str,
        *,
        turn_index: int,
        parsed: SpeakAgentOutput | None,
        answer: str,
        notes: list[str],
        cache: dict[str, Any],
    ) -> None:
        if not self.is_enabled(session_id):
            return
        output = parsed
        lines = [
            "",
            "=" * 72,
            f"[SPEAK TRACE] turn_done session={session_id} turn={turn_index}",
            "-" * 72,
            f"session_state={output.session_state if output else '—'}",
            f"answer_chars={len(answer)} recorded_notes={list(notes)}",
            f"speak={output.speak if output else ''}",
            f"thought={output.thought if output else ''}",
            f"actions={list(output.actions) if output else []}",
            f"raw_tail={(output.raw[-400:] if output and output.raw else '')}",
            "-" * 72,
            "【回合后本地缓存】",
            _format_cache(cache),
            "=" * 72,
            "",
        ]
        _print_block(lines)


def _format_cache(cache: dict[str, Any]) -> str:
    import json

    return json.dumps(cache, ensure_ascii=False, indent=2)


def _print_block(lines: list[str]) -> None:
    text = "\n".join(lines)
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


_TRACE = SpeakPromptTrace()


def get_prompt_trace() -> SpeakPromptTrace:
    return _TRACE
