"""全局线程租约注册表。

业务模块向本模块申请线程/运行令牌；infra 只负责登记、启动、统一 stop/join 与兜底回收。
不理解任务内容，不负责任务调度。
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class ThreadLease:
    """一次线程租约：持有底层 Thread 与可选协作停止钩子。"""

    def __init__(
        self,
        *,
        registry: ThreadRegistry,
        lease_id: str,
        owner: str,
        name: str,
        target: Callable[..., Any],
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        daemon: bool = True,
        stop: Callable[[], None] | None = None,
    ) -> None:
        self._registry = registry
        self.lease_id = lease_id
        self.owner = owner
        self.name = name
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}
        self._daemon = daemon
        self._stop_hook = stop
        self._stop_signaled = False
        self._still_alive = False
        self._started = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def thread(self) -> threading.Thread | None:
        return self._thread

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def still_alive(self) -> bool:
        return self._still_alive

    def start(self) -> None:
        with self._lock:
            if self._started:
                raise RuntimeError(f"thread lease already started: {self.name}")
            self._started = True
            self._thread = threading.Thread(
                target=self._run,
                name=self.name,
                daemon=self._daemon,
            )
            self._thread.start()

    def stop(self, timeout: float = 30.0) -> bool:
        """调用 stop hook 后 join。返回 True 表示线程已退出。"""
        with self._lock:
            if not self._stop_signaled and self._stop_hook is not None:
                self._stop_hook()
                self._stop_signaled = True
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        alive = self.is_alive()
        self._still_alive = alive
        if alive:
            logger.warning(
                "thread lease still alive after stop: owner=%s name=%s lease_id=%s",
                self.owner,
                self.name,
                self.lease_id,
            )
        else:
            self._registry._unregister(self.lease_id)
        return not alive

    def release(self) -> None:
        """线程自然结束后注销租约（不 join）。"""
        if self.is_alive():
            raise RuntimeError(f"cannot release live thread lease: {self.name}")
        self._registry._unregister(self.lease_id)

    def snapshot(self) -> dict[str, Any]:
        return {
            "lease_id": self.lease_id,
            "owner": self.owner,
            "name": self.name,
            "started": self._started,
            "alive": self.is_alive(),
            "still_alive": self._still_alive,
            "daemon": self._daemon,
        }

    def _run(self) -> None:
        try:
            self._target(*self._args, **self._kwargs)
        finally:
            self._registry._unregister(self.lease_id)


class ThreadRegistry:
    """按 owner 收束的线程租约注册表（进程级单例）。"""

    _instance: ThreadRegistry | None = None
    _init_lock = threading.Lock()

    def __init__(self) -> None:
        self._leases: dict[str, ThreadLease] = {}
        self._lock = threading.Lock()

    @classmethod
    def global_instance(cls) -> ThreadRegistry:
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        with cls._init_lock:
            if cls._instance is not None:
                cls._instance.stop_all(timeout=1.0)
                cls._instance = None

    def request(
        self,
        owner: str,
        name: str,
        target: Callable[..., Any],
        *,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        daemon: bool = True,
        stop: Callable[[], None] | None = None,
    ) -> ThreadLease:
        owner_key = owner.strip()
        name_key = name.strip()
        if not owner_key:
            raise ValueError("thread lease owner must be non-empty")
        if not name_key:
            raise ValueError("thread lease name must be non-empty")
        lease_id = uuid.uuid4().hex
        lease = ThreadLease(
            registry=self,
            lease_id=lease_id,
            owner=owner_key,
            name=name_key,
            target=target,
            args=args,
            kwargs=kwargs,
            daemon=daemon,
            stop=stop,
        )
        with self._lock:
            self._leases[lease_id] = lease
        return lease

    def stop_owner(self, owner: str, *, timeout: float = 30.0) -> list[ThreadLease]:
        owner_key = owner.strip()
        with self._lock:
            leases = [lease for lease in self._leases.values() if lease.owner == owner_key]
        still_alive: list[ThreadLease] = []
        for lease in leases:
            if not lease.stop(timeout=timeout):
                still_alive.append(lease)
        return still_alive

    def stop_all(self, *, timeout: float = 30.0) -> list[ThreadLease]:
        with self._lock:
            leases = list(self._leases.values())
        still_alive: list[ThreadLease] = []
        for lease in leases:
            if not lease.stop(timeout=timeout):
                still_alive.append(lease)
        return still_alive

    def leases_for(self, owner: str) -> list[ThreadLease]:
        owner_key = owner.strip()
        with self._lock:
            return [lease for lease in self._leases.values() if lease.owner == owner_key]

    def status(self, owner: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            leases = list(self._leases.values())
        if owner is not None:
            owner_key = owner.strip()
            leases = [lease for lease in leases if lease.owner == owner_key]
        return [lease.snapshot() for lease in leases]

    def _unregister(self, lease_id: str) -> None:
        with self._lock:
            self._leases.pop(lease_id, None)


def get_thread_registry() -> ThreadRegistry:
    return ThreadRegistry.global_instance()
