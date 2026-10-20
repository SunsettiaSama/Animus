from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from agent.soul.heartbeat.console_log import hb_debug
from agent.soul.heartbeat.policy import may_sleep
from agent.soul.heartbeat.schedule import (
    ChecklistItem,
    ChecklistRegistry,
    HeartbeatContext,
    resolve_target,
)
from config.soul.config import SoulConfig

if TYPE_CHECKING:
    from agent.soul.service import SoulService
    from .worker import SoulEvolutionWorker

logger = logging.getLogger(__name__)


@dataclass
class ChecklistRunResult:
    item_id: str
    domain: str
    action: str
    ok: bool
    detail: Any = None
    error: str = ""
    async_enqueued: bool = False


class HeartbeatOrchestrator:
    """心跳编排器：到期扫描 → 按注册契约调用 target。

    零模块知识：实现住在各域的 heartbeat 入口（见 wake-registration-prd），
    本类只负责到期判定、heavy 分流、避让策略与结果记录。
    """

    def __init__(
        self,
        soul: SoulService | None = None,
        checklist: ChecklistRegistry | None = None,
        *,
        soul_config: SoulConfig | None = None,
    ) -> None:
        self._soul = soul
        self._cfg = soul_config or SoulConfig.default()
        self._checklist = checklist or ChecklistRegistry()
        self._scheduler_engine = None
        self._worker: SoulEvolutionWorker | None = None
        self._vitals_provider = None  # module 注入的体征读口（可选）

    @property
    def soul_config(self) -> SoulConfig:
        return self._cfg

    @property
    def checklist(self) -> ChecklistRegistry:
        return self._checklist

    def set_soul_service(self, soul: SoulService | None) -> None:
        self._soul = soul
        if soul is not None:
            self._cfg = soul.config

    def set_scheduler_engine(self, engine) -> None:
        self._scheduler_engine = engine

    def set_worker(self, worker: SoulEvolutionWorker | None) -> None:
        self._worker = worker

    def set_vitals_provider(self, provider) -> None:
        """挂生命体征读口（module.vitals；未挂时避让策略直接放行）。"""
        self._vitals_provider = provider

    @staticmethod
    def is_heavy(item: ChecklistItem) -> bool:
        return bool(item.heavy)

    def run_due(self, *, exclude_item_ids: frozenset[str] = frozenset()) -> list[ChecklistRunResult]:
        if self._soul is None:
            return []

        now_mono = time.monotonic()
        now_dt = datetime.now(timezone.utc)
        results: list[ChecklistRunResult] = []

        for item in self._checklist.due(now_mono, now_dt):
            if item.id in exclude_item_ids:
                continue
            if self.is_heavy(item):
                result = self._enqueue_heavy(item, now_mono, now_dt)
            else:
                result = self.execute_item(item)
                if result.ok:
                    self._checklist.mark_run(item, now_mono, now_dt)
            results.append(result)
            hb_debug(
                logger,
                "[HeartbeatOrchestrator] %s/%s ok=%s async=%s",
                item.domain,
                item.action,
                result.ok,
                result.async_enqueued,
            )

        return results

    def run_due_item(self, item_id: str) -> ChecklistRunResult | None:
        if self._soul is None:
            return None

        item = self._checklist._items.get(item_id)
        if item is None or not item.enabled:
            return None

        now_mono = time.monotonic()
        now_dt = datetime.now(timezone.utc)
        if item.id not in {i.id for i in self._checklist.due(now_mono, now_dt)}:
            return None

        if self.is_heavy(item):
            result = self._enqueue_heavy(item, now_mono, now_dt)
        else:
            result = self.execute_item(item)
            if result.ok:
                self._checklist.mark_run(item, now_mono, now_dt)
        hb_debug(
            logger,
            "[HeartbeatOrchestrator] %s/%s ok=%s async=%s",
            item.domain,
            item.action,
            result.ok,
            result.async_enqueued,
        )
        return result

    def _enqueue_heavy(
        self,
        item: ChecklistItem,
        now_mono: float,
        now_dt: datetime,
    ) -> ChecklistRunResult:
        if self._worker is None:
            result = self.execute_item(item)
            if result.ok:
                self._checklist.mark_run(item, now_mono, now_dt)
            return result

        if not self._worker.enqueue(item):
            return ChecklistRunResult(
                item.id,
                item.domain,
                item.action,
                True,
                detail={"skipped": "already pending"},
            )

        self._checklist.mark_run(item, now_mono, now_dt)
        return ChecklistRunResult(
            item.id,
            item.domain,
            item.action,
            True,
            detail={"enqueued": True},
            async_enqueued=True,
        )

    # ── 通用执行：注册契约的唯一路径 ─────────────────────────────────────────

    def execute_item(self, item: ChecklistItem) -> ChecklistRunResult:
        if self._soul is None:
            return ChecklistRunResult(
                item.id, item.domain, item.action, False, error="no soul"
            )

        if item.avoid_when_speaking:
            ok, reason = may_sleep(self._vitals())
            if not ok:
                hb_debug(
                    logger,
                    "[HeartbeatOrchestrator] %s skipped - %s",
                    item.id,
                    reason,
                )
                return ChecklistRunResult(
                    item.id,
                    item.domain,
                    item.action,
                    True,
                    detail={"skipped": reason},
                )

        ctx = HeartbeatContext(
            soul=self._soul,
            orchestrator=self,
            scheduler_engine=self._scheduler_engine,
            vitals_provider=self._vitals_provider,
        )
        target = resolve_target(item.target, ctx)
        detail = target(dict(item.payload), ctx)
        return ChecklistRunResult(item.id, item.domain, item.action, True, detail=detail)

    def submit_heavy(self, item: ChecklistItem) -> bool:
        """提交一次性重任务（不进注册表、不 mark_run）。

        供域入口在运行期派生重活（如 story 演化过道）：固定 id 借 worker
        的 pending 去重天然防重入；worker 未接线时同步执行兜底。
        """
        if self._worker is None:
            self.execute_item(item)
            return True
        return self._worker.enqueue(item)

    def _vitals(self):
        provider = self._vitals_provider
        if provider is None:
            return None
        try:
            return provider()
        except Exception:  # noqa: BLE001 — 体征读失败不阻断既有调度
            logger.warning("[HeartbeatOrchestrator] vitals 读取失败", exc_info=True)
            return None
