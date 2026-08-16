from __future__ import annotations

import logging
import threading
import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from .channel_ids import live_session_id, normalize_channel_id
from .notify.events import make_create_ui_request_event, make_proactive_available_event
from .notify.ports import SpeakNotifyPort
from .stream.events import SpeakStreamEvent
from .stream.ports import SpeakStreamPort

logger = logging.getLogger(__name__)

_MAX_STREAM_PER_SESSION = 64
_MAX_NOTIFY = 64
_MAX_PROACTIVE = 32
_CREATE_UI_TIMEOUT_SEC = 8.0

SnapshotSink = Callable[[dict[str, Any]], None]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SpeakOutboundBus:
    """Speak 自有出站总线：proactive pending 唯一源 + 界面握手 + 快照。

    交付顺序：
    1) 已有可用 WS 界面 → 直接投递
    2) 无界面但有 SSE 订阅 → create_ui_request，等前端自动创建回执
    3) 不可达 / 拒绝 / 超时 → snapshot sink（未读历史）
    """

    def __init__(self, *, create_ui_timeout_sec: float = _CREATE_UI_TIMEOUT_SEC) -> None:
        self._lock = threading.RLock()
        self._stream_port: SpeakStreamPort | None = None
        self._notify_ports: list[SpeakNotifyPort] = []
        self._stream_pending: dict[str, deque[SpeakStreamEvent]] = defaultdict(deque)
        self._notify_pending: deque[dict[str, Any]] = deque()
        # channel_id → ordered delivery_ids
        self._channel_queue: dict[str, deque[str]] = defaultdict(deque)
        # delivery_id → payload
        self._proactive_by_id: dict[str, dict[str, Any]] = {}
        self._create_ui_timers: dict[str, threading.Timer] = {}
        self._create_ui_timeout_sec = float(create_ui_timeout_sec)
        self._snapshot_sink: SnapshotSink | None = None
        self._on_connection_ready: Callable[[str, str], None] | None = None

    def bind_stream_port(self, port: SpeakStreamPort | None) -> None:
        with self._lock:
            self._stream_port = port
            if port is None:
                return
            for sid, queue in list(self._stream_pending.items()):
                while queue:
                    event = queue.popleft()
                    port.emit(sid, event)
        binder = getattr(port, "bind_outbound_bus", None) if port is not None else None
        if callable(binder):
            binder(self)

    def bind_snapshot_sink(self, sink: SnapshotSink | None) -> None:
        with self._lock:
            self._snapshot_sink = sink

    def attach_notify_port(self, port: SpeakNotifyPort) -> None:
        with self._lock:
            if port not in self._notify_ports:
                self._notify_ports.append(port)
            pending = list(self._notify_pending)
            self._notify_pending.clear()
        for item in pending:
            self._publish_notify_item(item)

    def detach_notify_port(self, port: SpeakNotifyPort) -> None:
        with self._lock:
            self._notify_ports = [p for p in self._notify_ports if p is not port]

    @property
    def stream_port(self) -> SpeakStreamPort | None:
        with self._lock:
            return self._stream_port

    def publish_stream(self, session_id: str, event: SpeakStreamEvent) -> None:
        sid = session_id.strip()
        with self._lock:
            port = self._stream_port
            if port is None:
                queue = self._stream_pending[sid]
                queue.append(event)
                while len(queue) > _MAX_STREAM_PER_SESSION:
                    queue.popleft()
                return
        port.emit(sid, event)

    def publish_notify(self, item: dict[str, Any]) -> bool:
        return self._publish_notify_item(dict(item))

    def enqueue_proactive(self, payload: dict[str, Any]) -> dict[str, Any]:
        queued = self._normalize_payload(payload)
        did = str(queued["delivery_id"])
        cid = str(queued["channel_id"])
        with self._lock:
            existing = self._proactive_by_id.get(did)
            if existing is not None:
                status = str(existing.get("_status") or "")
                return {
                    "ok": True,
                    "delivered": status == "delivered",
                    "status": status or "duplicate",
                    "payload": dict(existing),
                }
            queued["_status"] = "pending"
            self._proactive_by_id[did] = queued
            bucket = self._channel_queue[cid]
            bucket.append(did)
            while len(bucket) > _MAX_PROACTIVE:
                old = bucket.popleft()
                self._proactive_by_id.pop(old, None)
                self._cancel_create_ui_timer_locked(old)

        delivered = self._try_deliver(did)
        if delivered:
            return {"ok": True, "delivered": True, "status": "delivered", "payload": queued}

        reached = self._request_create_ui(did)
        if reached:
            with self._lock:
                entry = self._proactive_by_id.get(did)
                if entry is not None and str(entry.get("_status")) == "pending":
                    entry["_status"] = "awaiting_ui"
                    self._arm_create_ui_timer_locked(did)
            return {
                "ok": True,
                "delivered": False,
                "status": "awaiting_ui",
                "payload": queued,
            }

        self._snapshot_delivery(did, reason="unreachable")
        return {
            "ok": True,
            "delivered": False,
            "status": "snapshotted",
            "payload": queued,
        }

    def resolve_create_ui(
        self,
        delivery_id: str,
        *,
        accepted: bool,
        channel_id: str = "",
        session_id: str = "",
    ) -> dict[str, Any]:
        did = delivery_id.strip()
        with self._lock:
            entry = self._proactive_by_id.get(did)
            if entry is None:
                return {"ok": False, "reason": "unknown_delivery"}
            self._cancel_create_ui_timer_locked(did)
            status = str(entry.get("_status") or "")
            if status in {"delivered", "snapshotted", "acked"}:
                return {"ok": True, "status": status, "delivered": status == "delivered"}
            if channel_id.strip():
                entry["channel_id"] = normalize_channel_id(
                    channel_id,
                    session_id or str(entry.get("session_id") or ""),
                )
            if session_id.strip():
                entry["session_id"] = live_session_id(
                    str(entry.get("channel_id") or ""),
                    session_id,
                )

        if not accepted:
            self._snapshot_delivery(did, reason="create_ui_rejected")
            return {"ok": True, "status": "snapshotted", "delivered": False}

        delivered = self._try_deliver(did)
        if delivered:
            return {"ok": True, "status": "delivered", "delivered": True}

        # 前端已接受但 WS 尚未挂上：短等连接就绪；此处先标 accepted，由 on_connection_ready 推送
        with self._lock:
            entry = self._proactive_by_id.get(did)
            if entry is not None and str(entry.get("_status")) not in {
                "delivered",
                "snapshotted",
                "acked",
            }:
                entry["_status"] = "ui_accepted"
                self._arm_create_ui_timer_locked(did)
        return {"ok": True, "status": "ui_accepted", "delivered": False}

    def on_connection_ready(self, session_id: str, channel_id: str = "") -> None:
        cid = normalize_channel_id(channel_id, session_id)
        if not cid:
            return
        with self._lock:
            ids = list(self._channel_queue.get(cid, ()))
        for did in ids:
            with self._lock:
                entry = self._proactive_by_id.get(did)
                if entry is None:
                    continue
                status = str(entry.get("_status") or "")
                # 已推出成功即已消费，不再因重连重推
                if status not in {"pending", "awaiting_ui", "ui_accepted"}:
                    continue
            self._try_deliver(did)

    def acknowledge_proactive(
        self,
        delivery_id: str,
        *,
        session_id: str = "",
        channel_id: str = "",
    ) -> bool:
        did = delivery_id.strip()
        if not did:
            return False
        with self._lock:
            entry = self._proactive_by_id.pop(did, None)
            self._cancel_create_ui_timer_locked(did)
            if entry is None:
                # 推出成功时已消费；ack 幂等
                return True
            cid = normalize_channel_id(
                channel_id or str(entry.get("channel_id") or ""),
                session_id or str(entry.get("session_id") or ""),
            )
            bucket = self._channel_queue.get(cid)
            if bucket is not None:
                self._channel_queue[cid] = deque(x for x in bucket if x != did)
                if not self._channel_queue[cid]:
                    self._channel_queue.pop(cid, None)
        port = self.stream_port
        ack = getattr(port, "acknowledge_proactive", None) if port is not None else None
        if callable(ack):
            ack(
                str(session_id or entry.get("session_id") or ""),
                cid,
                did,
            )
        return True

    def take_proactive(
        self,
        session_id: str,
        channel_id: str = "",
    ) -> dict[str, Any] | None:
        cid = normalize_channel_id(channel_id, session_id)
        with self._lock:
            bucket = self._channel_queue.get(cid)
            if not bucket:
                return None
            did = bucket.popleft()
            entry = self._proactive_by_id.pop(did, None)
            self._cancel_create_ui_timer_locked(did)
            if not bucket:
                self._channel_queue.pop(cid, None)
            return dict(entry) if entry is not None else None

    def pending_proactive_notifications(self, channel_id: str = "") -> list[dict[str, Any]]:
        cid = normalize_channel_id(channel_id)
        out: list[dict[str, Any]] = []
        with self._lock:
            for pending_cid, bucket in self._channel_queue.items():
                if cid and pending_cid != cid:
                    continue
                if not bucket:
                    continue
                entry = self._proactive_by_id.get(bucket[0])
                if entry is None:
                    continue
                status = str(entry.get("_status") or "")
                if status in {"delivered", "acked", "snapshotted"}:
                    continue
                out.append(
                    make_create_ui_request_event(
                        session_id=str(entry.get("session_id") or ""),
                        channel_id=pending_cid,
                        proactive_intent_id=str(entry.get("proactive_intent_id") or ""),
                        delivery_id=str(entry.get("delivery_id") or ""),
                        source=str(entry.get("source") or ""),
                        wait_reply=bool(entry.get("wait_reply", False)),
                    )
                )
        return out

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "stream_bound": self._stream_port is not None,
                "notify_ports": len(self._notify_ports),
                "stream_pending_sessions": {
                    sid: len(q) for sid, q in self._stream_pending.items() if q
                },
                "notify_pending": len(self._notify_pending),
                "proactive_pending": {
                    cid: len(q) for cid, q in self._channel_queue.items() if q
                },
                "proactive_statuses": {
                    did: str(entry.get("_status") or "")
                    for did, entry in self._proactive_by_id.items()
                },
            }

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        queued = dict(payload)
        raw_sid = str(queued.get("session_id", "") or "").strip()
        raw_cid = str(queued.get("channel_id", "") or "").strip()
        if not raw_cid:
            raise ValueError("proactive payload requires channel_id")
        cid = normalize_channel_id(raw_cid, raw_sid)
        if not cid:
            raise ValueError("proactive payload requires channel_id")
        sid = live_session_id(cid, raw_sid)
        queued["session_id"] = sid
        queued["channel_id"] = cid
        queued["delivery_id"] = str(
            queued.get("delivery_id")
            or queued.get("proactive_intent_id")
            or uuid.uuid4()
        )
        queued.setdefault("agent_initiated", True)
        queued.setdefault("create_window", True)
        # speak 发生时刻：入队时固化，后续重放/渲染不得改写成「现在」
        stamp = str(queued.get("created_at") or "").strip()
        queued["created_at"] = stamp or _now_iso()
        return queued

    def _consume_delivery_locked(self, delivery_id: str) -> None:
        """推出成功即消费：移出 pending，重连不再重推。"""
        entry = self._proactive_by_id.pop(delivery_id, None)
        self._cancel_create_ui_timer_locked(delivery_id)
        if entry is None:
            return
        cid = str(entry.get("channel_id") or "")
        bucket = self._channel_queue.get(cid)
        if bucket is not None:
            self._channel_queue[cid] = deque(x for x in bucket if x != delivery_id)
            if not self._channel_queue[cid]:
                self._channel_queue.pop(cid, None)

    def _try_deliver(self, delivery_id: str) -> bool:
        with self._lock:
            entry = self._proactive_by_id.get(delivery_id)
            if entry is None:
                return False
            status = str(entry.get("_status") or "")
            if status in {"snapshotted", "acked", "delivered"}:
                return False
            port = self._stream_port
            payload = dict(entry)
        if port is None:
            return False
        has_conn = False
        checker = getattr(port, "has_connection", None)
        if checker is None:
            has_conn = True
        else:
            has_conn = bool(
                checker(
                    str(payload.get("session_id") or ""),
                    channel_id=str(payload.get("channel_id") or ""),
                )
                if _accepts_channel_kw(checker)
                else checker(str(payload.get("session_id") or ""))
            )
        if not has_conn:
            return False
        deliver = getattr(port, "enqueue_proactive", None)
        delivered = False
        created_at = str(payload.get("created_at") or "").strip()
        if callable(deliver):
            delivered = bool(deliver(payload))
        else:
            text = str(payload.get("message", "") or "").strip()
            if text:
                meta = {
                    "server_initiated": True,
                    "proactive": True,
                    "agent_initiated": True,
                    "create_window": bool(payload.get("create_window", True)),
                    "proactive_intent_id": payload.get("proactive_intent_id", ""),
                    "delivery_id": payload.get("delivery_id", ""),
                    "source": payload.get("source", ""),
                    "created_at": created_at,
                }
                sid = str(payload.get("session_id") or "")
                self.publish_stream(
                    sid,
                    SpeakStreamEvent(kind="speak", text=text, meta=meta),
                )
                self.publish_stream(
                    sid,
                    SpeakStreamEvent(
                        kind="finish",
                        text="",
                        final=True,
                        meta=meta,
                    ),
                )
                delivered = True
        if delivered:
            with self._lock:
                self._consume_delivery_locked(delivery_id)
            logger.info(
                "[speak_outbound] proactive delivered session=%s channel=%s delivery_id=%s",
                payload.get("session_id"),
                payload.get("channel_id"),
                delivery_id,
            )
        return delivered

    def _request_create_ui(self, delivery_id: str) -> bool:
        with self._lock:
            entry = self._proactive_by_id.get(delivery_id)
            if entry is None:
                return False
            event = make_create_ui_request_event(
                session_id=str(entry.get("session_id") or ""),
                channel_id=str(entry.get("channel_id") or ""),
                proactive_intent_id=str(entry.get("proactive_intent_id") or ""),
                delivery_id=delivery_id,
                source=str(entry.get("source") or ""),
                wait_reply=bool(entry.get("wait_reply", False)),
            )
        reached = self._publish_notify_item(event)
        logger.info(
            "[speak_outbound] create_ui_request session=%s channel=%s delivery_id=%s reached=%s",
            event.get("session_id"),
            event.get("channel_id"),
            delivery_id,
            reached,
        )
        return reached

    def _snapshot_delivery(self, delivery_id: str, *, reason: str) -> None:
        with self._lock:
            entry = self._proactive_by_id.get(delivery_id)
            if entry is None:
                return
            status = str(entry.get("_status") or "")
            if status in {"delivered", "snapshotted", "acked"}:
                return
            entry["_status"] = "snapshotted"
            entry["_snapshot_reason"] = reason
            self._cancel_create_ui_timer_locked(delivery_id)
            payload = dict(entry)
            sink = self._snapshot_sink
            cid = str(payload.get("channel_id") or "")
            bucket = self._channel_queue.get(cid)
            if bucket is not None:
                self._channel_queue[cid] = deque(x for x in bucket if x != delivery_id)
                if not self._channel_queue[cid]:
                    self._channel_queue.pop(cid, None)
            self._proactive_by_id.pop(delivery_id, None)
        # 兼容旧 SSE 监听：附带 proactive_available 元数据
        self._publish_notify_item(
            make_proactive_available_event(
                session_id=str(payload.get("session_id") or ""),
                channel_id=str(payload.get("channel_id") or ""),
                proactive_intent_id=str(payload.get("proactive_intent_id") or ""),
                delivery_id=delivery_id,
                source=str(payload.get("source") or ""),
                wait_reply=bool(payload.get("wait_reply", False)),
                online=False,
                create_window=bool(payload.get("create_window", True)),
            )
        )
        if sink is not None:
            sink(payload)
        logger.info(
            "[speak_outbound] snapshotted delivery_id=%s reason=%s channel=%s",
            delivery_id,
            reason,
            payload.get("channel_id"),
        )

    def _arm_create_ui_timer_locked(self, delivery_id: str) -> None:
        self._cancel_create_ui_timer_locked(delivery_id)
        timer = threading.Timer(
            self._create_ui_timeout_sec,
            self._on_create_ui_timeout,
            args=(delivery_id,),
        )
        timer.daemon = True
        self._create_ui_timers[delivery_id] = timer
        timer.start()

    def _cancel_create_ui_timer_locked(self, delivery_id: str) -> None:
        timer = self._create_ui_timers.pop(delivery_id, None)
        if timer is not None:
            timer.cancel()

    def _on_create_ui_timeout(self, delivery_id: str) -> None:
        with self._lock:
            entry = self._proactive_by_id.get(delivery_id)
            if entry is None:
                return
            status = str(entry.get("_status") or "")
            if status not in {"awaiting_ui", "ui_accepted", "pending"}:
                return
        self._snapshot_delivery(delivery_id, reason="create_ui_timeout")

    def _publish_notify_item(self, item: dict[str, Any]) -> bool:
        payload = dict(item)
        with self._lock:
            ports = list(self._notify_ports)
            if not ports:
                self._notify_pending.append(payload)
                while len(self._notify_pending) > _MAX_NOTIFY:
                    self._notify_pending.popleft()
                return False
        reached = False
        for port in ports:
            result = port.publish(payload)
            if result is None or bool(result):
                reached = True
        return reached


def _accepts_channel_kw(fn: Any) -> bool:
    code = getattr(fn, "__code__", None)
    if code is None:
        unbound = getattr(fn, "__func__", None)
        code = getattr(unbound, "__code__", None) if unbound is not None else None
    if code is None:
        return False
    names = code.co_varnames[: code.co_argcount]
    return "channel_id" in names
