"""全局节点运行时管理器。

节点（RunnableNode）不自己创建线程，而是向本模块的单例申请资源，
由统一的线程池调度 executor 和 verifier 的执行，实现跨节点的资源上限控制。

两个独立线程池
--------------
executor_pool   运行 ManifestExecutor.run()（TAO 循环，CPU/IO 密集）
verifier_pool   运行 NodeVerifier.verify()（另一个 TAO 循环，通常比 executor 轻）

单例创建
--------
程序启动时调用 NodeRuntimeManager.configure(executor_threads, verifier_threads)；
未调用时首次访问 global_instance() 会以默认参数自动创建。

使用示例
--------
    from infra.node_runtime import NodeRuntimeManager

    mgr = NodeRuntimeManager.global_instance()
    future = mgr.submit_executor(my_fn, arg1, arg2)
    result = future.result()
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable


class NodeRuntimeManager:
    """节点执行与校验的全局线程池管理器（单例）。"""

    _instance: NodeRuntimeManager | None = None
    _init_lock = threading.Lock()

    def __init__(
        self,
        executor_threads: int = 8,
        verifier_threads: int = 4,
        doc_threads: int = 1,
    ) -> None:
        self._executor_pool = ThreadPoolExecutor(
            max_workers=executor_threads,
            thread_name_prefix="node-exec",
        )
        self._verifier_pool = ThreadPoolExecutor(
            max_workers=verifier_threads,
            thread_name_prefix="node-verify",
        )
        # 单线程 FIFO：文档/日志写入顺序保证，不抢 exec/verify 资源
        self._doc_pool = ThreadPoolExecutor(
            max_workers=doc_threads,
            thread_name_prefix="node-doc",
        )
        self._executor_threads = executor_threads
        self._verifier_threads = verifier_threads
        self._doc_threads = doc_threads

    # ── 单例接口 ──────────────────────────────────────────────────────────────

    @classmethod
    def global_instance(cls) -> NodeRuntimeManager:
        """返回全局单例；未配置时以默认参数创建。"""
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def configure(
        cls,
        executor_threads: int = 8,
        verifier_threads: int = 4,
        doc_threads: int = 1,
    ) -> NodeRuntimeManager:
        """程序启动阶段调用，显式配置并初始化单例。

        若已初始化则抛出 RuntimeError，防止意外覆盖。
        """
        with cls._init_lock:
            if cls._instance is not None:
                raise RuntimeError(
                    "NodeRuntimeManager already initialized. "
                    "Call reset() first if reconfiguration is intentional."
                )
            cls._instance = cls(executor_threads, verifier_threads, doc_threads)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """关闭现有单例并清除引用（测试 / 重启场景使用）。"""
        with cls._init_lock:
            if cls._instance is not None:
                cls._instance.shutdown(wait=False)
                cls._instance = None

    # ── 资源申请 ──────────────────────────────────────────────────────────────

    def submit_executor(self, fn: Callable, *args: Any, **kwargs: Any) -> Future:
        """向 executor 线程池提交任务，返回 Future。"""
        return self._executor_pool.submit(fn, *args, **kwargs)

    def submit_verifier(self, fn: Callable, *args: Any, **kwargs: Any) -> Future:
        """向 verifier 线程池提交任务，返回 Future。"""
        return self._verifier_pool.submit(fn, *args, **kwargs)

    def submit_doc_write(self, fn: Callable, *args: Any, **kwargs: Any) -> Future:
        """向文档写入池提交任务，fire-and-forget，不阻塞 run() 返回。

        单线程 FIFO：保证同一节点的多次写入顺序。
        失败不向调用方传播——文档写入失败不应影响节点状态。
        """
        def _safe_call() -> None:
            fn(*args, **kwargs)

        return self._doc_pool.submit(_safe_call)

    # ── 状态查询 ──────────────────────────────────────────────────────────────

    @property
    def executor_threads(self) -> int:
        return self._executor_threads

    @property
    def verifier_threads(self) -> int:
        return self._verifier_threads

    # ── 生命周期 ──────────────────────────────────────────────────────────────

    def shutdown(self, wait: bool = True) -> None:
        """优雅关闭全部线程池。doc_pool 总是等待写入完成再关闭。"""
        self._executor_pool.shutdown(wait=wait, cancel_futures=not wait)
        self._verifier_pool.shutdown(wait=wait, cancel_futures=not wait)
        self._doc_pool.shutdown(wait=True)   # 文档写入必须等完成，不丢数据
