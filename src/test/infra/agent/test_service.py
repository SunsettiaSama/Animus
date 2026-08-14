from __future__ import annotations

import threading

from langchain_core.messages import BaseMessage

from infra.agent import AgentService, BaseAgent
from infra.agent.unit import UserUnit
from infra.threading import ThreadRegistry


class _ScriptedLLM:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[list[BaseMessage]] = []
        self.thread_names: list[str] = []

    def generate_messages(self, messages: list[BaseMessage]) -> str:
        self.calls.append(list(messages))
        self.thread_names.append(threading.current_thread().name)
        if not self.replies:
            raise RuntimeError("no more scripted replies")
        return self.replies.pop(0)


class _FakeRunner:
    def __init__(self) -> None:
        self.calls: list[list[dict]] = []
        self.thread_names: list[str] = []

    def run(self, calls: list[dict]) -> list[dict]:
        self.calls.append(list(calls))
        self.thread_names.append(threading.current_thread().name)
        return [
            {"tool": str(c.get("action") or ""), "observation": f"ok:{c.get('action')}"}
            for c in calls
        ]


def setup_function() -> None:
    ThreadRegistry.reset()


def teardown_function() -> None:
    ThreadRegistry.reset()


def test_creating_instance_starts_dedicated_service_thread():
    llm = _ScriptedLLM(
        ['<T>x</T><A>[{"action":"finish","args":{"answer":"hi"}}]</A>']
    )
    svc = AgentService(llm, _FakeRunner(), name="agent-a", max_steps=2)
    assert svc.status()["state"] == "running"
    assert svc.status()["name"] == "agent-a"

    answer = svc.run("q").result(timeout=2.0)
    assert answer == "hi"
    assert llm.thread_names
    assert llm.thread_names[0] == "agent-a"
    assert llm.thread_names[0] != threading.current_thread().name

    svc.stop()
    assert svc.status()["state"] == "stopped"


def test_each_instance_is_its_own_service():
    llm_a = _ScriptedLLM(
        ['<T>a</T><A>[{"action":"finish","args":{"answer":"A"}}]</A>']
    )
    llm_b = _ScriptedLLM(
        ['<T>b</T><A>[{"action":"finish","args":{"answer":"B"}}]</A>']
    )
    a = AgentService(llm_a, _FakeRunner(), name="agent-left", max_steps=2)
    b = AgentService(llm_b, _FakeRunner(), name="agent-right", max_steps=2)

    fa = a.run("left")
    fb = b.run("right")
    assert fa.result(timeout=2.0) == "A"
    assert fb.result(timeout=2.0) == "B"
    assert llm_a.thread_names == ["agent-left"]
    assert llm_b.thread_names == ["agent-right"]
    assert a.name != b.name

    a.stop()
    b.stop()


def test_inject_and_step_run_on_service_thread():
    llm = _ScriptedLLM(
        [
            '<T>s</T><A>[{"action":"noop","args":{}}]</A>',
            '<T>f</T><A>[{"action":"finish","args":{"answer":"done"}}]</A>',
        ]
    )
    runner = _FakeRunner()
    svc = AgentService(llm, runner, name="agent-step", max_steps=4)
    svc.add_user("go").result(timeout=2.0)
    first = svc.step().result(timeout=2.0)
    assert first.done is False
    assert isinstance(svc.timeline.units[0], UserUnit)

    card = UserUnit(text="导演插话", source="director")
    card.kind = "rhythm_card"
    svc.inject(card).result(timeout=2.0)
    second = svc.step().result(timeout=2.0)
    assert second.done is True
    assert second.answer == "done"
    assert all(name == "agent-step" for name in llm.thread_names)
    assert all(name == "agent-step" for name in runner.thread_names)
    svc.stop()


def test_base_agent_remains_sync_primitive():
    llm = _ScriptedLLM(
        ['<T>x</T><A>[{"action":"finish","args":{"answer":"sync"}}]</A>']
    )
    agent = BaseAgent(llm, _FakeRunner(), max_steps=2)
    assert agent.run("q") == "sync"
    assert llm.thread_names[0] == threading.current_thread().name
