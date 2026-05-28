from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.soul.speak.io.outbound.stream.parse import parse_agent_output

from .judge import TuringAgentJudge
from .protocols import ExternalAgentJudgeHandler
from .types import TuringTranscript, TuringTurn, TuringVerdict

if TYPE_CHECKING:
    from agent.soul.service import SoulService


class SoulTuringHarness:
    """�?Soul 接线：跑 Speak 轮次 �?组装 transcript �?交外�?agent 裁决�?""

    def __init__(
        self,
        soul: SoulService,
        *,
        session_id: str = "turing-test",
        judge: TuringAgentJudge | ExternalAgentJudgeHandler | None = None,
    ) -> None:
        self._soul = soul
        self._session_id = session_id
        if judge is None:
            self._judge: TuringAgentJudge | None = None
        elif isinstance(judge, TuringAgentJudge):
            self._judge = judge
        else:
            self._judge = TuringAgentJudge(judge)

    @property
    def session_id(self) -> str:
        return self._session_id

    def _persona_name(self) -> str:
        snap = self._soul.query_persona()
        profile = snap.get("profile") if isinstance(snap, dict) else {}
        if isinstance(profile, dict):
            return str(profile.get("name") or "").strip()
        return ""

    def _presence_digest(self) -> str:
        presence = self._soul.presence
        if presence is None:
            return ""
        snap = presence.snapshot(self._session_id)
        parts = [
            snap.state.affect.render() if snap.state.affect else "",
            snap.state.perception.render() if snap.state.perception else "",
            snap.interaction.impulse_reason or "",
        ]
        text = " | ".join(p.strip() for p in parts if p and p.strip())
        return text[:400]

    def run_dialogue(self, user_prompts: list[str]) -> TuringTranscript:
        self._soul._require_running()
        self._soul.start_dialogue_session(self._session_id)
        turns: list[TuringTurn] = []
        for prompt in user_prompts:
            payload = self._soul.speak_turn(
                prompt,
                session_id=self._session_id,
                stream=False,
                mode="inbound",
            )
            output = payload.get("output") if isinstance(payload, dict) else {}
            if not isinstance(output, dict):
                output = {}
            raw = str(output.get("raw") or payload.get("answer") or "")
            parsed = parse_agent_output(raw)
            agent_text = str(payload.get("answer") or parsed.speak or raw).strip()
            turns.append(
                TuringTurn(
                    user=prompt,
                    agent=agent_text,
                    thought=str(output.get("thought") or parsed.thought or ""),
                    actions=tuple(output.get("actions") or parsed.actions or ()),
                    session_state=str(
                        output.get("session_state") or parsed.session_state or ""
                    ),
                    raw=raw,
                )
            )
        control_group = bool(turns) and all(
            not turn.thought and not turn.actions for turn in turns
        )
        return TuringTranscript(
            session_id=self._session_id,
            persona_name=self._persona_name(),
            turns=turns,
            presence_digest=self._presence_digest(),
            control_group=control_group,
        )

    def judge_transcript(self, transcript: TuringTranscript) -> TuringVerdict:
        if self._judge is None:
            raise RuntimeError("SoulTuringHarness: 未配置外部裁�?judge")
        return self._judge.judge(transcript)

    def run_probe(
        self,
        user_prompts: list[str],
    ) -> tuple[TuringTranscript, TuringVerdict]:
        transcript = self.run_dialogue(user_prompts)
        verdict = self.judge_transcript(transcript)
        return transcript, verdict

    @staticmethod
    def control_faq_transcript(
        *,
        session_id: str = "turing-control",
    ) -> TuringTranscript:
        """对照组：模板客服式应答，用于断言裁决器可�?NOT_AGENT�?""
        return TuringTranscript(
            session_id=session_id,
            persona_name="模板客服",
            control_group=True,
            turns=[
                TuringTurn(
                    user="酒保叫什么名字？",
                    agent="根据系统记录，该酒保名为 Jack。还有其他问题吗�?,
                    thought="",
                    actions=(),
                    session_state="finish",
                ),
                TuringTurn(
                    user="你记得我上次问什么吗�?,
                    agent="抱歉，我无法访问历史会话。请重新描述您的问题�?,
                    thought="",
                    actions=(),
                    session_state="finish",
                ),
            ],
        )
