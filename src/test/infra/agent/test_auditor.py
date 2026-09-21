from __future__ import annotations

import time
from collections import deque

from infra.agent.auditor import (
    AuditVerdict,
    AuditorConfig,
    OutputAuditor,
    _AuditTask,
)
from infra.threading import ThreadRegistry


class _ScriptedAuditLLM:
    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.replies:
            raise RuntimeError("no more scripted replies")
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _wait_for(condition, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def setup_function() -> None:
    ThreadRegistry.reset()


def teardown_function() -> None:
    ThreadRegistry.reset()


def test_parse_verdict_faithful_and_unfaithful():
    auditor = OutputAuditor(_ScriptedAuditLLM([]))

    good = auditor._parse_verdict(
        '{"faithful": true, "unsupported": [], "reason": "无事实主张"}',
        latency_ms=1.0,
        model="m",
    )
    assert good.faithful is True
    assert good.unsupported == []

    bad = auditor._parse_verdict(
        '审查结果：{"faithful": false, "unsupported": ["编造1998年的旅行", "虚构宠物猫"], '
        '"reason": "两条无依据"} 以上。',
        latency_ms=2.0,
        model="m",
    )
    assert bad.faithful is False
    assert bad.unsupported == ["编造1998年的旅行", "虚构宠物猫"]
    assert bad.reason == "两条无依据"
    assert bad.model == "m"


def test_parse_verdict_tolerates_bad_output():
    auditor = OutputAuditor(_ScriptedAuditLLM([]))

    none_json = auditor._parse_verdict("没有 JSON", latency_ms=0.0, model="m")
    assert none_json.faithful is None
    assert none_json.reason == "no_json_in_verdict"

    broken = auditor._parse_verdict('{"faithful": 是}', latency_ms=0.0, model="m")
    assert broken.faithful is None
    assert broken.reason == "invalid_verdict_json"

    non_bool = auditor._parse_verdict(
        '{"faithful": "yes", "unsupported": "不是列表"}', latency_ms=0.0, model="m"
    )
    assert non_bool.faithful is None
    assert non_bool.unsupported == []


def test_llm_exception_degrades_to_inconclusive():
    llm = _ScriptedAuditLLM([RuntimeError("boom")])
    auditor = OutputAuditor(llm)
    verdict = auditor._audit_one(
        _AuditTask(context="c", output="o", step_index=1, scope="finish")
    )
    assert verdict.faithful is None
    assert verdict.reason == "llm_error:RuntimeError"


def test_prompt_carries_context_and_output():
    llm = _ScriptedAuditLLM(['{"faithful": true, "unsupported": [], "reason": ""}'])
    auditor = OutputAuditor(llm)
    auditor._audit_one(
        _AuditTask(context="上下文证据", output="模型产出", step_index=0, scope="finish")
    )
    assert "上下文证据" in llm.prompts[0]
    assert "模型产出" in llm.prompts[0]


def test_submit_truncates_context_and_output():
    llm = _ScriptedAuditLLM(['{"faithful": true, "unsupported": [], "reason": ""}'])
    auditor = OutputAuditor(
        llm, AuditorConfig(enabled=True, max_context_chars=10, max_output_chars=5)
    )
    try:
        auditor.submit(context="A" * 100, output="B" * 100)
        assert _wait_for(lambda: len(auditor.verdicts) == 1)
        prompt = llm.prompts[0]
        assert "A" * 10 in prompt
        assert "A" * 11 not in prompt
        assert "B" * 5 in prompt
        assert "B" * 6 not in prompt
    finally:
        auditor.stop()


def test_disabled_auditor_ignores_submit_and_never_starts_thread():
    llm = _ScriptedAuditLLM(['{"faithful": true, "unsupported": [], "reason": ""}'])
    auditor = OutputAuditor(llm, AuditorConfig(enabled=False))
    auditor.submit(context="c", output="o", step_index=1)
    assert len(auditor.verdicts) == 0
    assert llm.prompts == []
    status = auditor.status()
    assert status["enabled"] is False
    assert status["state"] == "stopped"
    assert status["queued"] == 0


def test_submit_async_records_verdict():
    llm = _ScriptedAuditLLM(
        ['{"faithful": false, "unsupported": ["凭空提到的上周聚会"], "reason": "上下文无此事"}']
    )
    auditor = OutputAuditor(llm, AuditorConfig(enabled=True))
    try:
        auditor.submit(
            context="用户: 今天聊猫",
            output="<T>..</T><O>我上周参加了聚会</O>",
            step_index=2,
            scope="finish",
        )
        assert _wait_for(lambda: len(auditor.verdicts) == 1)
        task, verdict = auditor.verdicts[0]
        assert verdict.faithful is False
        assert verdict.unsupported == ["凭空提到的上周聚会"]
        assert task.step_index == 2
        assert task.scope == "finish"
        assert "今天聊猫" in llm.prompts[0]
        assert "我上周参加了聚会" in llm.prompts[0]
        assert auditor.status()["audited"] == 1
    finally:
        auditor.stop()


def test_stop_terminates_worker_thread():
    llm = _ScriptedAuditLLM(['{"faithful": true, "unsupported": [], "reason": ""}'])
    auditor = OutputAuditor(llm, AuditorConfig(enabled=True))
    auditor.submit(context="c", output="o")
    assert _wait_for(lambda: len(auditor.verdicts) == 1)
    auditor.stop(timeout=5.0)
    assert auditor.status()["state"] == "stopped"


def test_verdict_ring_buffer_is_bounded():
    replies = [
        '{"faithful": true, "unsupported": [], "reason": ""}' for _ in range(6)
    ]
    llm = _ScriptedAuditLLM(replies)
    auditor = OutputAuditor(llm, AuditorConfig(enabled=True))
    try:
        for i in range(6):
            auditor.submit(context=f"c{i}", output="o")
        assert _wait_for(lambda: len(auditor.verdicts) == 6)
        assert isinstance(auditor.verdicts, deque)
        assert auditor.verdicts.maxlen == 64
    finally:
        auditor.stop()


def test_audit_verdict_defaults():
    verdict = AuditVerdict()
    assert verdict.faithful is None
    assert verdict.unsupported == []
