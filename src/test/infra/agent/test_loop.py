from __future__ import annotations

import time
from dataclasses import dataclass

from langchain_core.messages import BaseMessage, HumanMessage

from infra.agent import BaseAgent, ObservationUnit, Timeline, Unit, UserUnit
from infra.agent.auditor import AuditorConfig, OutputAuditor
from infra.agent.parse import parse_tao_output
from infra.agent.review import WhitelistCallReview


@dataclass
class RhythmCardUnit(Unit):
    card: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            self.kind = "rhythm_card"
        if not self.source:
            self.source = "director"

    def render(self) -> str:
        text = self.card.strip()
        return f"[节奏卡片]\n{text}" if text else ""


class _ScriptedLLM:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[list[BaseMessage]] = []

    def generate_messages(self, messages: list[BaseMessage]) -> str:
        self.calls.append(list(messages))
        if not self.replies:
            raise RuntimeError("no more scripted replies")
        return self.replies.pop(0)


class _FakeRunner:
    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    def run(self, calls: list[dict]) -> list[dict]:
        self.calls.append(list(calls))
        out: list[dict] = []
        for call in calls:
            action = str(call.get("action") or "")
            out.append({"tool": action, "observation": f"ok:{action}"})
        return out


class _AuditLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return '{"faithful": true, "unsupported": [], "reason": "ok"}'


def _wait_for(condition, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_parse_finish_and_tool():
    finish = parse_tao_output(
        '<T>结束</T><A>[{"action":"finish","args":{"answer":"你好"}}]</A>'
    )
    assert finish.ok
    assert finish.is_finish
    assert finish.answer == "你好"

    tool = parse_tao_output(
        '<T>搜</T><A>[{"action":"web_search","args":{"q":"x"}}]</A>'
    )
    assert tool.ok
    assert not tool.is_finish
    assert tool.action == "web_search"

    bad = parse_tao_output("没有标签")
    assert not bad.ok
    assert "missing" in bad.error


def test_run_user_ta_obs_finish():
    llm = _ScriptedLLM(
        [
            '<T>先搜</T><A>[{"action":"web_search","args":{"q":"x"}}]</A>',
            '<T>答</T><A>[{"action":"finish","args":{"answer":"完成"}}]</A><O>完成</O>',
        ]
    )
    runner = _FakeRunner()
    agent = BaseAgent(llm, runner, system="你是基础 agent", max_steps=4)
    answer = agent.run("你好")
    assert answer == "完成"
    assert len(runner.calls) == 1
    assert runner.calls[0][0]["action"] == "web_search"
    assert agent.finished
    kinds = [u.kind for u in agent.timeline.units]
    assert kinds == ["user", "thought_action", "observation", "thought_action"]


def test_finish_does_not_call_action_runner():
    llm = _ScriptedLLM(
        ['<T>直接结束</T><A>[{"action":"finish","args":{"answer":"ok"}}]</A>']
    )
    runner = _FakeRunner()
    agent = BaseAgent(llm, runner, max_steps=2)
    assert agent.run("hi") == "ok"
    assert runner.calls == []


def test_parse_failure_writes_observation_and_continues():
    llm = _ScriptedLLM(
        [
            "这不是合法输出",
            '<T>修好了</T><A>[{"action":"finish","args":{"answer":"好了"}}]</A>',
        ]
    )
    runner = _FakeRunner()
    agent = BaseAgent(llm, runner, max_steps=3)
    agent.add_user("问")
    first = agent.step()
    assert first.done is False
    assert first.observations
    assert first.observations[0].source == "parse"
    assert any(
        isinstance(u, ObservationUnit) and u.source == "parse"
        for u in agent.timeline.units
    )
    second = agent.step()
    assert second.done is True
    assert second.answer == "好了"
    assert runner.calls == []


def test_custom_unit_injected_between_steps_appears_in_next_prompt():
    llm = _ScriptedLLM(
        [
            '<T>第一步</T><A>[{"action":"noop","args":{}}]</A>',
            '<T>看到卡片</T><A>[{"action":"finish","args":{"answer":"收到节奏"}}]</A>',
        ]
    )
    runner = _FakeRunner()
    agent = BaseAgent(llm, runner, max_steps=4)
    agent.add_user("开始")
    first = agent.step()
    assert first.done is False

    agent.inject(RhythmCardUnit(card="轻声开口"))
    second = agent.step()
    assert second.done is True

    assert len(llm.calls) == 2
    second_human = next(
        m for m in llm.calls[1] if isinstance(m, HumanMessage)
    )
    content = str(second_human.content)
    assert "[节奏卡片]" in content
    assert "轻声开口" in content
    # first prompt must not contain the card
    first_human = next(m for m in llm.calls[0] if isinstance(m, HumanMessage))
    assert "[节奏卡片]" not in str(first_human.content)


def test_max_steps_exhausted_raises():
    llm = _ScriptedLLM(
        [
            '<T>a</T><A>[{"action":"noop","args":{}}]</A>',
            '<T>b</T><A>[{"action":"noop","args":{}}]</A>',
        ]
    )
    runner = _FakeRunner()
    agent = BaseAgent(llm, runner, max_steps=2)
    raised = False
    try:
        agent.run("x")
    except RuntimeError as exc:
        raised = True
        assert "max_steps" in str(exc)
    assert raised


def test_reset_clears_session():
    llm = _ScriptedLLM(
        ['<T>x</T><A>[{"action":"finish","args":{"answer":"1"}}]</A>']
    )
    agent = BaseAgent(llm, _FakeRunner(), max_steps=2)
    agent.run("q1")
    assert isinstance(agent.timeline.units[0], UserUnit)
    agent.reset()
    assert agent.timeline.units == ()
    assert agent.steps_taken == 0
    assert agent.finished is False


def test_review_blocks_batch_until_self_corrected():
    llm = _ScriptedLLM(
        [
            '<T>搜</T><A>[{"action":"web_searc","args":{"q":"x"}}]</A>',
            '<T>改用正确工具</T><A>[{"action":"web_search","args":{"q":"x"}}]</A>',
            '<T>答</T><A>[{"action":"finish","args":{"answer":"完成"}}]</A>',
        ]
    )
    runner = _FakeRunner()
    review = WhitelistCallReview(frozenset({"web_search"}))
    agent = BaseAgent(llm, runner, system="s", max_steps=5, call_review=review)
    agent.add_user("问")

    first = agent.step()
    assert first.done is False
    assert runner.calls == []  # 整批拦截：一步都没有执行
    assert first.review is not None and not first.review.ok
    assert first.observations[0].source == "review"
    assert first.observations[0].tool == "review"
    assert "web_search" in first.observations[0].observation

    second = agent.step()
    assert second.done is False
    assert second.review is not None and second.review.ok
    assert len(runner.calls) == 1  # 修正后放行
    assert "ok:web_search" in second.observations[0].observation

    third = agent.step()
    assert third.done is True and third.answer == "完成"
    kinds = [u.kind for u in agent.timeline.units]
    assert kinds == [
        "user",
        "thought_action",
        "observation",  # review 拦截
        "thought_action",
        "observation",  # 工具结果
        "thought_action",
    ]
    review_units = [u for u in agent.timeline.units if isinstance(u, ObservationUnit) and u.source == "review"]
    assert len(review_units) == 1


def test_no_review_by_default_passthrough():
    llm = _ScriptedLLM(
        ['<T>a</T><A>[{"action":"anything_at_all","args":{}}]</A>']
    )
    runner = _FakeRunner()
    agent = BaseAgent(llm, runner, max_steps=2)
    agent.add_user("q")
    result = agent.step()
    assert result.done is False
    assert result.review is None
    assert len(runner.calls) == 1


def test_auditor_fires_on_finish_only_by_default():
    llm = _ScriptedLLM(
        [
            '<T>搜</T><A>[{"action":"web_search","args":{"q":"x"}}]</A>',
            '<T>答</T><A>[{"action":"finish","args":{"answer":"完成"}}]</A>',
        ]
    )
    audit_llm = _AuditLLM()
    auditor = OutputAuditor(audit_llm, AuditorConfig(enabled=True))
    agent = BaseAgent(llm, _FakeRunner(), max_steps=4, auditor=auditor)
    try:
        agent.add_user("问")
        first = agent.step()
        assert first.done is False
        assert audit_llm.prompts == []  # 默认 scope=finish，非 finish 步不审

        second = agent.step()
        assert second.done is True
        assert _wait_for(lambda: len(auditor.verdicts) == 1)
        task, verdict = auditor.verdicts[0]
        assert task.scope == "finish"
        assert verdict.faithful is True
        prompt = audit_llm.prompts[0]
        assert "问" in prompt  # 上下文含用户输入
        assert "ok:web_search" in prompt  # 上下文含工具观察
        assert "答" in prompt  # 产出为模型原文
    finally:
        auditor.stop()


def test_auditor_every_step_scope():
    llm = _ScriptedLLM(
        [
            '<T>搜</T><A>[{"action":"web_search","args":{"q":"x"}}]</A>',
            '<T>答</T><A>[{"action":"finish","args":{"answer":"完成"}}]</A>',
        ]
    )
    audit_llm = _AuditLLM()
    auditor = OutputAuditor(audit_llm, AuditorConfig(enabled=True, scope="every_step"))
    agent = BaseAgent(llm, _FakeRunner(), max_steps=4, auditor=auditor)
    try:
        agent.add_user("问")
        agent.step()
        agent.step()
        assert _wait_for(lambda: len(auditor.verdicts) == 2)
        assert [t.scope for t, _ in auditor.verdicts] == ["step", "finish"]
    finally:
        auditor.stop()


def test_disabled_auditor_is_inert_in_loop():
    llm = _ScriptedLLM(
        ['<T>x</T><A>[{"action":"finish","args":{"answer":"1"}}]</A>']
    )
    audit_llm = _AuditLLM()
    auditor = OutputAuditor(audit_llm, AuditorConfig(enabled=False))
    agent = BaseAgent(llm, _FakeRunner(), max_steps=2, auditor=auditor)
    agent.run("q")
    time.sleep(0.1)
    assert audit_llm.prompts == []
    assert auditor.status()["state"] == "stopped"
