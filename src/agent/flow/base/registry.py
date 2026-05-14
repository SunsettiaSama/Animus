from __future__ import annotations

from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .components.protocols import (
        BaseAtomicPlanner, BaseAtomicReviewer, ManifestExecutor, NodeVerifier,
    )

# factory(tool_package | None) -> ManifestExecutor
ExecutorFactory = Callable[["str | None"], "ManifestExecutor"]
# factory() -> NodeVerifier
VerifierFactory = Callable[[], "NodeVerifier"]
# factory(llm_cfg_path) -> BaseAtomicPlanner
AtomicPlannerFactory = Callable[[str], "BaseAtomicPlanner"]
# factory(llm_cfg_path) -> BaseAtomicReviewer
AtomicReviewerFactory = Callable[[str], "BaseAtomicReviewer"]


class NodeRegistry:
    """节点执行器与校验器的全局注册表。

    职责
    ----
    · executor_factory  — 给定 tool_package 名称，返回对应的 ManifestExecutor 实例。
    · verifier_factory  — 可选，返回 NodeVerifier 实例；未注册时 build_verifier() 返回 None，
                          RunnableNode 会以 VerificationResult.skip() 兜底。
    · known_packages    — 已注册的工具包名称集合，供 Orchestrator 校验
                          NodeManifest.tool_package 合法性。

    使用方式
    --------
    启动时调用 ``register_defaults(llm_cfg_path)`` 注入默认实现；
    各集群可用 ``get_registry()`` 取到全局实例后覆盖特定工厂。
    """

    def __init__(self) -> None:
        self._executor_factory: ExecutorFactory | None = None
        self._verifier_factory: VerifierFactory | None = None
        self._atomic_planner_factory: AtomicPlannerFactory | None = None
        self._atomic_reviewer_factory: AtomicReviewerFactory | None = None
        self._known_packages: set[str] = set()

    # ── 注册 ──────────────────────────────────────────────────────────────────

    def set_executor_factory(self, factory: ExecutorFactory) -> None:
        """注册执行器工厂。factory(tool_package) -> ManifestExecutor。"""
        self._executor_factory = factory

    def set_verifier_factory(self, factory: VerifierFactory) -> None:
        """注册校验器工厂。factory() -> NodeVerifier。"""
        self._verifier_factory = factory

    def set_atomic_planner_factory(self, factory: AtomicPlannerFactory) -> None:
        """注册原子规划器工厂。factory(llm_cfg_path) -> BaseAtomicPlanner。"""
        self._atomic_planner_factory = factory

    def set_atomic_reviewer_factory(self, factory: AtomicReviewerFactory) -> None:
        """注册原子审查器工厂。factory(llm_cfg_path) -> BaseAtomicReviewer。"""
        self._atomic_reviewer_factory = factory

    def register_packages(self, *names: str) -> None:
        """注册已知工具包名称。"""
        self._known_packages.update(names)

    # ── 构建 ──────────────────────────────────────────────────────────────────

    def build_executor(self, tool_package: str | None = None) -> "ManifestExecutor":
        """根据 tool_package 名称返回 ManifestExecutor 实例。

        Raises
        ------
        RuntimeError
            未调用 register_defaults() 或 set_executor_factory() 时。
        """
        if self._executor_factory is None:
            raise RuntimeError(
                "No executor factory registered. "
                "Call register_defaults(llm_cfg_path) before using NodeRegistry."
            )
        return self._executor_factory(tool_package)

    def build_verifier(self) -> "NodeVerifier | None":
        """返回 NodeVerifier 实例；未注册时返回 None（触发 skip 兜底）。"""
        if self._verifier_factory is None:
            return None
        return self._verifier_factory()

    def build_atomic_planner(self, llm_cfg_path: str) -> "BaseAtomicPlanner | None":
        """返回 BaseAtomicPlanner 实例；未注册时返回 None。"""
        if self._atomic_planner_factory is None:
            return None
        return self._atomic_planner_factory(llm_cfg_path)

    def build_atomic_reviewer(self, llm_cfg_path: str) -> "BaseAtomicReviewer | None":
        """返回 BaseAtomicReviewer 实例；未注册时返回 None。"""
        if self._atomic_reviewer_factory is None:
            return None
        return self._atomic_reviewer_factory(llm_cfg_path)

    # ── 查询 ──────────────────────────────────────────────────────────────────

    def known_packages(self) -> frozenset[str]:
        return frozenset(self._known_packages)

    def is_package_known(self, name: str) -> bool:
        return name in self._known_packages

    def has_executor(self) -> bool:
        return self._executor_factory is not None

    def has_verifier(self) -> bool:
        return self._verifier_factory is not None

    def has_atomic_planner(self) -> bool:
        return self._atomic_planner_factory is not None

    def has_atomic_reviewer(self) -> bool:
        return self._atomic_reviewer_factory is not None


# ── 全局单例 ──────────────────────────────────────────────────────────────────

_registry = NodeRegistry()


def get_registry() -> NodeRegistry:
    """返回进程级全局注册表单例。"""
    return _registry
