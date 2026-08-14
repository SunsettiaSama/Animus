"""Agent 实例即服务：每个实例独占一条 OS 线程 + FIFO 队列，缩短调用方等待。"""
from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

from infra.agent.loop import BaseAgent
from infra.agent.ports import ActionRunner
from infra.agent.timeline import Timeline
from infra.agent.unit import Unit
from infra.llm.llm import BaseLLM
from infra.threading import ThreadLease, get_thread_registry

_WAKE_POLL_SEC = 0.5


class AgentService:
    """一个 AgentService 实例 = 一个常驻服务线程。

    BaseAgent 仍是 loop 原语；本类负责把该实例挂到独立线程上，由操作系统调度，
    调用方通过 submit_* 入队，不占用调用线程做 LLM/工具。
    """

    def __init__(
        self,
        llm: BaseLLM,
        action_runner: ActionRunner,
        *,
        system: str = "",
        max_steps: int = 8,
        timeline: Timeline | None = None,
        name: str = "",
        owner: str = "agent",
        auto_start: bool = True,
    ) -> None:
        self._agent = BaseAgent(
            llm,
            action_runner,
            system=system,
            max_steps=max_steps,
            timeline=timeline,
        )
        self._owner = owner.strip() or "agent"
        self._name = (name.strip() or f"agent-service-{id(self):x}")
        self._tasks: list[Callable[[], None]] = []
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._lease: ThreadLease | None = None
        if auto_start:
            self.start()

    @property
    def agent(self) -> BaseAgent:
        return self._agent

    @property
    def name(self) -> str:
        return self._name

    @property
    def owner(self) -> str:
        return self._owner

    @property
    def timeline(self) -> Timeline:
        return self._agent.timeline

    def start(self) -> None:
        if self._lease is not None and self._lease.is_alive():
            return
        self._stop.clear()
        lease = get_thread_registry().request(
            self._owner,
            self._name,
            self._run,
            daemon=True,
            stop=self._signal_stop,
        )
        lease.start()
        self._lease = lease

    def stop(self, timeout: float = 30.0) -> None:
        self._signal_stop()
        if self._lease is not None:
            self._lease.stop(timeout=timeout)
            self._lease = None

    def status(self) -> dict[str, Any]:
        alive = self._lease is not None and self._lease.is_alive()
        with self._lock:
            queued = len(self._tasks)
        return {
            "state": "running" if alive else "stopped",
            "queued": queued,
            "owner": self._owner,
            "name": self._name,
            "steps_taken": self._agent.steps_taken,
            "finished": self._agent.finished,
        }

    def set_system(self, system: str) -> Future:
        return self._submit(lambda: self._agent.set_system(system))

    def reset(self) -> Future:
        return self._submit(self._agent.reset)

    def inject(self, unit: Unit) -> Future:
        return self._submit(lambda: self._agent.inject(unit))

    def add_user(self, text: str, **kwargs: Any) -> Future:
        return self._submit(lambda: self._agent.add_user(text, **kwargs))

    def step(self) -> Future:
        return self._submit(self._agent.step)

    def run(self, question: str) -> Future:
        return self._submit(lambda: self._agent.run(question))

    def _submit(self, task: Callable[[], object]) -> Future:
        if self._lease is None or not self._lease.is_alive():
            raise RuntimeError(f"AgentService not running: {self._name}")
        future: Future = Future()

        def _wrapper() -> None:
            if future.cancelled():
                return
            try:
                future.set_result(task())
            except BaseException as exc:
                future.set_exception(exc)

        self._enqueue(_wrapper)
        return future

    def _enqueue(self, task: Callable[[], None]) -> None:
        with self._lock:
            self._tasks.append(task)
        self._wake.set()

    def _signal_stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=_WAKE_POLL_SEC)
            self._wake.clear()
            with self._lock:
                pending, self._tasks = self._tasks, []
            for task in pending:
                if self._stop.is_set():
                    break
                task()
