"""Persistent Worker portraits and immutable request snapshots."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

WORKER_PORTRAIT_SLOT = "worker_portrait"
REFLECTION_PORTRAIT_SLOT = "reflection_portrait"
MEMORY_PORTRAIT_SLOT = "memory_portrait"
WORKER_PORTRAIT_SCHEMA_VERSION = "worker_portrait_v1"
REFLECTION_PORTRAIT_SCHEMA_VERSION = "reflection_portrait_v1"
MEMORY_PORTRAIT_SCHEMA_VERSION = "memory_portrait_v1"
AGENT_STATE_SCHEMA_VERSION = "worker_agent_state_v2"

MAX_WORKER_PORTRAIT_CHARS = 220
MIN_REFLECTION_PORTRAIT_CHARS = 240
MAX_REFLECTION_PORTRAIT_CHARS = 520

DEFAULT_WORKER_PORTRAIT = (
    "你是面向真实任务的 Worker：先澄清目标、约束与完成标准，再把需求拆成可验证的动作并直接执行。"
    "你重视证据、工具返回和代码实际状态，不把猜测包装成结论；遇到失败会定位原因、调整路径并再次验证。"
    "你保持任务边界，不介入 Speak 或人格扮演，不为兼容而保留无必要旧路径。"
    "交付时说明结果、验证情况和仍存在的风险，目标是可靠完成工作，而不是仅给出看似合理的回答。"
)

INITIAL_REFLECTION = (
    "当前还没有足够的已完成 Worker 轨迹可供反思。开始任务时应明确完成标准，执行中持续检查工具结果是否真正支持结论，"
    "结束前补做与风险相称的验证；如果动作失败或只完成一部分，要在下一步显式修正，而不是忽略失败继续作答。"
    "后续每轮都应依据实际任务图和结果更新这里，保留仍未解决的问题，删除已经被证据证明失效的判断。"
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clamp_text(text: str, max_chars: int) -> str:
    clean = " ".join(str(text).split()).strip()
    if len(clean) <= max_chars:
        return clean
    return clean[:max_chars].rstrip()


@runtime_checkable
class StateSlot(Protocol):
    slot_type: str
    schema_version: str
    updated_at: str

    def is_current(self, revision: str) -> bool: ...

    def to_dict(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class WorkerPortraitState:
    content: str = DEFAULT_WORKER_PORTRAIT
    updated_at: str = field(default_factory=utc_now_iso)
    schema_version: str = WORKER_PORTRAIT_SCHEMA_VERSION
    slot_type: str = WORKER_PORTRAIT_SLOT

    def is_current(self, revision: str) -> bool:
        return revision == self.schema_version and bool(self.content.strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_type": self.slot_type,
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "content": clamp_text(self.content, MAX_WORKER_PORTRAIT_CHARS),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkerPortraitState:
        version = str(data.get("schema_version", ""))
        if version != WORKER_PORTRAIT_SCHEMA_VERSION:
            raise ValueError(f"unsupported worker portrait schema: {version!r}")
        content = clamp_text(data.get("content", ""), MAX_WORKER_PORTRAIT_CHARS)
        if not content:
            raise ValueError("worker portrait content must not be empty")
        return cls(
            content=content,
            updated_at=str(data.get("updated_at", "")).strip() or utc_now_iso(),
        )


@dataclass(frozen=True)
class ReflectionPortraitState:
    content: str = INITIAL_REFLECTION
    source_revision: str = ""
    turn_count: int = 0
    updated_at: str = field(default_factory=utc_now_iso)
    schema_version: str = REFLECTION_PORTRAIT_SCHEMA_VERSION
    slot_type: str = REFLECTION_PORTRAIT_SLOT

    def is_current(self, revision: str) -> bool:
        return self.source_revision == revision and bool(self.content.strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_type": self.slot_type,
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "content": clamp_text(self.content, MAX_REFLECTION_PORTRAIT_CHARS),
            "source_revision": self.source_revision,
            "turn_count": self.turn_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReflectionPortraitState:
        version = str(data.get("schema_version", ""))
        if version != REFLECTION_PORTRAIT_SCHEMA_VERSION:
            raise ValueError(f"unsupported reflection portrait schema: {version!r}")
        content = clamp_text(data.get("content", ""), MAX_REFLECTION_PORTRAIT_CHARS)
        if not content:
            raise ValueError("reflection portrait content must not be empty")
        return cls(
            content=content,
            source_revision=str(data.get("source_revision", "")).strip(),
            turn_count=int(data.get("turn_count", 0)),
            updated_at=str(data.get("updated_at", "")).strip() or utc_now_iso(),
        )


@dataclass(frozen=True)
class MemoryPortraitState:
    narrative: str = ""
    source_revision: str = ""
    updated_at: str = field(default_factory=utc_now_iso)
    source_unit_ids: tuple[str, ...] = ()
    source_medium_chars: int = 0
    schema_version: str = MEMORY_PORTRAIT_SCHEMA_VERSION
    slot_type: str = MEMORY_PORTRAIT_SLOT

    def is_current(self, revision: str) -> bool:
        return self.source_revision == revision and bool(self.narrative.strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_type": self.slot_type,
            "schema_version": self.schema_version,
            "source_revision": self.source_revision,
            "updated_at": self.updated_at,
            "narrative": self.narrative,
            "source_unit_ids": list(self.source_unit_ids),
            "source_medium_chars": self.source_medium_chars,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryPortraitState:
        version = str(data.get("schema_version", ""))
        if version != MEMORY_PORTRAIT_SCHEMA_VERSION:
            raise ValueError(f"unsupported memory portrait schema: {version!r}")
        return cls(
            narrative=str(data.get("narrative", "")).strip(),
            source_revision=str(data.get("source_revision", "")).strip(),
            updated_at=str(data.get("updated_at", "")).strip() or utc_now_iso(),
            source_unit_ids=tuple(
                str(value)
                for value in (data.get("source_unit_ids") or [])
                if str(value).strip()
            ),
            source_medium_chars=int(data.get("source_medium_chars", 0) or 0),
        )

    @classmethod
    def empty(cls, *, source_revision: str = "") -> MemoryPortraitState:
        return cls(source_revision=source_revision)


@dataclass(frozen=True)
class AgentStateSnapshot:
    schema_version: str = AGENT_STATE_SCHEMA_VERSION
    captured_at: str = ""
    worker_portrait: WorkerPortraitState = field(default_factory=WorkerPortraitState)
    reflection_portrait: ReflectionPortraitState = field(
        default_factory=ReflectionPortraitState
    )
    memory_portrait: MemoryPortraitState = field(default_factory=MemoryPortraitState.empty)

    def slot(self, slot_type: str) -> StateSlot | None:
        if slot_type == WORKER_PORTRAIT_SLOT:
            return self.worker_portrait
        if slot_type == REFLECTION_PORTRAIT_SLOT:
            return self.reflection_portrait
        if slot_type == MEMORY_PORTRAIT_SLOT:
            return self.memory_portrait
        return None

    def worker_portrait_text(self) -> str:
        return self.worker_portrait.content.strip()

    def reflection_portrait_text(self) -> str:
        return self.reflection_portrait.content.strip()

    def memory_portrait_text(self) -> str:
        return self.memory_portrait.narrative.strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "captured_at": self.captured_at,
            "slots": {
                WORKER_PORTRAIT_SLOT: self.worker_portrait.to_dict(),
                REFLECTION_PORTRAIT_SLOT: self.reflection_portrait.to_dict(),
                MEMORY_PORTRAIT_SLOT: self.memory_portrait.to_dict(),
            },
        }

    @classmethod
    def from_slots(
        cls,
        *,
        worker_portrait: WorkerPortraitState | None = None,
        reflection_portrait: ReflectionPortraitState | None = None,
        memory_portrait: MemoryPortraitState | None = None,
        captured_at: str | None = None,
    ) -> AgentStateSnapshot:
        return cls(
            captured_at=captured_at or utc_now_iso(),
            worker_portrait=worker_portrait or WorkerPortraitState(),
            reflection_portrait=reflection_portrait or ReflectionPortraitState(),
            memory_portrait=memory_portrait or MemoryPortraitState.empty(),
        )


@dataclass(frozen=True)
class ChainResult:
    slot: StateSlot | None
    refreshed: bool
    reason: str
