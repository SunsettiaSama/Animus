"""L1 探针层基座：soul 各部位的只读采样。

铁律：探针绝不抛异常——读不到（部位缺失/内部异常）一律折叠为
``ok=False``（unknown），由 vitals 层如实标注。心跳是唤起线，
探测动作本身不允许成为故障源。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProbeReading:
    name: str
    ok: bool
    fields: dict[str, Any] = field(default_factory=dict)


class SoulProbe:
    """探针模板基类：子类实现 ``_sample()``；``sample()`` 负责兜异常。"""

    name: str = "probe"

    def sample(self) -> ProbeReading:
        try:
            return ProbeReading(name=self.name, ok=True, fields=self._sample())
        except Exception:  # noqa: BLE001 — 探针永不抛
            logger.exception("[probe:%s] 采样失败（按 unknown 处理）", self.name)
            return ProbeReading(name=self.name, ok=False)

    def _sample(self) -> dict[str, Any]:  # pragma: no cover - 子类实现
        raise NotImplementedError(f"probe {self.name!r} 未实现 _sample")
