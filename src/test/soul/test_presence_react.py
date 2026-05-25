from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent.soul.presence.interface.egress.react.actions import ReactAction
from agent.soul.presence.interface.egress.react.chunker import split_text_chunks
from agent.soul.presence.interface.egress.react.context import SessionContextRetriever
from agent.soul.presence.interface.egress.react.parser import parse_action_field
from agent.soul.presence.interface.egress.react.speak_outbound import PresenceReactOutbound
from agent.soul.presence.interface.egress.request import SpeakRequest
from agent.soul.presence.fsm.expectation.package import ShareFoldedPackage
from agent.soul.presence.share_desire import ShareDesire
from agent.soul.presence.transition.expectation import Expectation
from config.soul.presence.interface_config import InterfaceReactConfig


class _StubEmbedder:
    def embed(self, text: str) -> list[float]:
        if "工作记忆" in text:
            return [1.0, 0.0]
        if "全量对话" in text:
            return [0.0, 1.0]
        return [0.5, 0.5]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


def test_parse_action_field_supports_action_args_and_typo():
    call = parse_action_field({
        "thought": "回忆一下",
        "action": {
            "action": "memory_recall",
            "acion_args": {"query": "架构"},
        },
    })
    assert call is not None
    assert call.action == "memory_recall"
    assert call.action_args["query"] == "架构"


def test_split_text_chunks_overlap():
    text = "a" * 1000
    chunks = split_text_chunks(text, chunk_size=400, overlap=80)
    assert len(chunks) >= 2
    assert all(len(c) <= 400 for c in chunks)


def test_session_context_retriever_ranks_relevant_chunk():
    soul = MagicMock()
    snap = MagicMock()
    snap.state.affect.narrative = "平静"
    snap.state.cognition.working_memory = "用户正在问架构"
    soul.presence.snapshot.return_value = snap

    dialogue = MagicMock()
    dialogue.session.turns = []
    dialogue.session.direction.value = "inbound"
    dialogue.session.outbound_message = ""
    dialogue.working_memory_text.return_value = "用户：讲讲架构\n我：好的"
    soul.experience.dialogue.state.return_value = dialogue

    retriever = SessionContextRetriever(
        soul,
        embedder=_StubEmbedder(),
        cfg=InterfaceReactConfig(session_context_top_k=1, chunk_size=200, chunk_overlap=20),
    )
    result = retriever.retrieve("tao", query="架构设计")
    assert result.chunks
    assert result.injected_text


def test_speak_outbound_blocks_proactive_when_required():
    soul = MagicMock()
    snap = MagicMock()
    snap.expectation.value = Expectation.required.value
    soul.presence.snapshot.return_value = snap

    outbound = PresenceReactOutbound(soul)
    result = outbound.deliver_agent_message(
        session_id="tao",
        message="想聊聊",
        wait_reply=True,
        append=False,
    )
    assert result["ok"] is False
    assert result["blocked"] is True
    soul.record_dialogue_turn.assert_not_called()


def test_speak_outbound_handle_expectation_append():
    soul = MagicMock()
    snap = MagicMock()
    snap.expectation.value = Expectation.optional.value
    soul.presence.snapshot.return_value = snap
    soul.start_dialogue_session.return_value = {"ok": True}
    soul.record_dialogue_turn.return_value = {"ok": True}

    outbound = PresenceReactOutbound(soul)
    request = SpeakRequest(
        session_id="tao",
        reason="补充一句",
        impulse_level=0.4,
        share_desire=ShareDesire.moderate,
        expectation=Expectation.optional,
        package=ShareFoldedPackage(
            summary="补充一句",
            entries=(),
            peak_salience=0.0,
            total_salience=0.0,
            peak_share_desire=ShareDesire.moderate,
            count=0,
        ),
        source="expectation_scan:append",
        wait_reply=False,
    )
    result = outbound.handle(request)
    assert result["ok"] is True
    assert result["append"] is True
    soul.record_dialogue_turn.assert_called_once()
    soul.presence.bind.assert_called_once_with("tao", expectation=Expectation.optional)


def test_parse_action_rejects_empty():
    assert parse_action_field({"action": {"action": ""}}) is None
    assert parse_action_field({}) is None
