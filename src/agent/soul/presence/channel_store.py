from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agent.soul.presence.state.dynamic.expectation.queue import ShareIntent, ShareIntentQueue


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ShareProductionAnnotation:
    """单次 agent 产出的分享/擢升标注（写入 channel 本地 jsonl）。"""

    ts: str = ""
    session_id: str = ""
    channel_id: str = ""
    unit_id: str = ""
    source: str = ""
    decided: bool = False
    enqueue_share: bool = False
    push_to_user: bool = False
    share_content: str = ""
    share_why: str = ""
    share_desire: str = "mild"
    promote_to_memory: bool = False
    impression_intensity: float = 0.0
    impression_why: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ShareProductionAnnotation:
        return cls(
            ts=str(d.get("ts", "") or ""),
            session_id=str(d.get("session_id", "") or ""),
            channel_id=str(d.get("channel_id", "") or ""),
            unit_id=str(d.get("unit_id", "") or ""),
            source=str(d.get("source", "") or ""),
            decided=bool(d.get("decided", d.get("annotation_decided", False))),
            enqueue_share=bool(d.get("enqueue_share", False)),
            push_to_user=bool(d.get("push_to_user", False)),
            share_content=str(d.get("share_content", "") or ""),
            share_why=str(d.get("share_why", "") or ""),
            share_desire=str(d.get("share_desire", "mild") or "mild"),
            promote_to_memory=bool(d.get("promote_to_memory", False)),
            impression_intensity=float(d.get("impression_intensity", 0.0) or 0.0),
            impression_why=str(d.get("impression_why", "") or ""),
            note=str(d.get("note", "") or ""),
        )

    @classmethod
    def undecided(
        cls,
        *,
        session_id: str,
        channel_id: str = "",
        unit_id: str = "",
        source: str = "",
        note: str = "undecided",
    ) -> ShareProductionAnnotation:
        return cls(
            ts=_now_iso(),
            session_id=session_id,
            channel_id=channel_id,
            unit_id=unit_id,
            source=source,
            decided=False,
            note=note,
        )


@dataclass
class ChannelShareState:
    """channel 分享权威态（队列 + 待推送标记）。"""

    channel_id: str
    share_queue: ShareIntentQueue = field(default_factory=ShareIntentQueue)
    pending_push: bool = False
    last_share_why: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "channel_id": self.channel_id,
            "share_queue": self.share_queue.to_dict(),
            "pending_push": self.pending_push,
            "last_share_why": self.last_share_why,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict, *, channel_id: str) -> ChannelShareState:
        return cls(
            channel_id=channel_id,
            share_queue=ShareIntentQueue.from_dict(d.get("share_queue") or {}),
            pending_push=bool(d.get("pending_push", False)),
            last_share_why=str(d.get("last_share_why", "") or ""),
            updated_at=str(d.get("updated_at", "") or ""),
        )


class ChannelShareSnapshotStore:
    """`.react/life/channels/{channel_id}/` 下的分享权威存储。"""

    def __init__(self, life_dir: str) -> None:
        self._root = Path(life_dir) / "channels"

    def channel_dir(self, channel_id: str) -> Path:
        cid = channel_id.strip()
        if not cid:
            raise ValueError("channel_id 为空，无法定位 channel 快照目录")
        path = self._root / cid
        path.mkdir(parents=True, exist_ok=True)
        return path

    def load_share_state(self, channel_id: str) -> ChannelShareState:
        cid = channel_id.strip()
        if not cid:
            return ChannelShareState(channel_id="")
        path = self.channel_dir(cid) / "share_state.json"
        if not path.exists():
            return ChannelShareState(channel_id=cid)
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return ChannelShareState.from_dict(raw or {}, channel_id=cid)

    def save_share_state(self, state: ChannelShareState) -> None:
        cid = state.channel_id.strip()
        if not cid:
            raise ValueError("channel_id 为空，无法保存 share_state")
        state.updated_at = _now_iso()
        path = self.channel_dir(cid) / "share_state.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)

    def append_annotation(self, annotation: ShareProductionAnnotation) -> None:
        cid = annotation.channel_id.strip()
        if not cid:
            # 无目标 channel：记入 life 待分享池目录
            cid = "_life_pool"
            annotation.channel_id = cid
        if not annotation.ts:
            annotation.ts = _now_iso()
        path = self.channel_dir(cid) / "share_annotations.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(annotation.to_dict(), ensure_ascii=False) + "\n")

    def archive_intents(
        self,
        channel_id: str,
        intents: list[ShareIntent],
        *,
        reason: str,
    ) -> None:
        cid = channel_id.strip()
        if not cid or not intents:
            return
        path = self.channel_dir(cid) / "share_archive.jsonl"
        ts = _now_iso()
        with open(path, "a", encoding="utf-8") as f:
            for intent in intents:
                payload = {
                    "ts": ts,
                    "reason": reason,
                    "intent": intent.to_dict(),
                }
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
