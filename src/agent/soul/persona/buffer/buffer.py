from __future__ import annotations

from datetime import datetime, timezone

from .trace import ClusterSignal


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    text = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


class ExperienceBuffer:
    """Persona buffer：仅累积聚类主题元数据，供月度 self_concept 漂移调度。"""

    def __init__(self, signals: list[ClusterSignal] | None = None) -> None:
        self._signals: list[ClusterSignal] = list(signals or [])

    @property
    def signals(self) -> list[ClusterSignal]:
        return list(self._signals)

    def is_empty(self) -> bool:
        return not self._signals

    def append(self, signal: ClusterSignal) -> ClusterSignal:
        self._signals.append(signal)
        return signal

    def pending(self) -> list[ClusterSignal]:
        return [s for s in self._signals if not s.consolidated]

    def pending_for_month(self, month: str) -> list[ClusterSignal]:
        """返回指定 ``YYYY-MM`` 内 recorded_at 且未 consolidated 的信号。"""
        out: list[ClusterSignal] = []
        for signal in self.pending():
            dt = _parse_iso(signal.recorded_at)
            if dt is None:
                continue
            if dt.strftime("%Y-%m") == month:
                out.append(signal)
        return out

    def mark_consolidated(self, signal_ids: list[str], *, at: str | None = None) -> int:
        ids = set(signal_ids)
        marked = 0
        stamp = at or datetime.now(timezone.utc).isoformat()
        for signal in self._signals:
            if signal.id in ids and not signal.consolidated:
                signal.consolidated = True
                signal.consolidated_at = stamp
                marked += 1
        return marked

    def clear(self) -> None:
        self._signals.clear()

    def summary(self) -> dict:
        pending = self.pending()
        return {
            "total": len(self._signals),
            "pending": len(pending),
            "recent_themes": [
                s.theme for s in pending[-5:] if s.theme.strip()
            ],
        }

    def snapshot(self, *, include_signals: bool = False) -> dict:
        data = self.summary()
        if include_signals:
            data["signals"] = [s.to_dict() for s in self._signals]
        return data

    def to_dicts(self) -> list[dict]:
        return [s.to_dict() for s in self._signals]

    @classmethod
    def from_dicts(cls, items: list[dict]) -> ExperienceBuffer:
        return cls([ClusterSignal.from_dict(item) for item in items])
