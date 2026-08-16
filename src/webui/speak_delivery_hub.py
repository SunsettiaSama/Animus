from __future__ import annotations

import asyncio
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from agent.soul.speak.io.outbound.channel_ids import live_session_id, normalize_channel_id
from agent.soul.speak.io.outbound.stream.events import SpeakStreamEvent


@dataclass
class _Connection:
    session_id: str
    channel_id: str
    gen_id: str
    port: Any
    put_payload: Callable[[dict[str, Any]], None]
    server_turn_open: bool = False
    server_text: list[str] = field(default_factory=list)
    server_events: list[dict[str, Any]] = field(default_factory=list)
    queued_proactive: deque[dict[str, Any]] = field(default_factory=deque)
    active_delivery_id: str = ""


class WebUISpeakDeliveryHub:
    """把 Speak 出站路由到精确的 WebUI WS 连接；不持有持久 pending。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._connections: dict[str, _Connection] = {}  # channel_id → connection
        self._client_turns: set[str] = set()
        self._outbound_bus: Any | None = None

    def bind_outbound_bus(self, bus: Any | None) -> None:
        with self._lock:
            self._outbound_bus = bus

    def register(
        self,
        *,
        session_id: str,
        channel_id: str,
        gen_id: str,
        port: Any,
        put_payload: Callable[[dict[str, Any]], None],
    ) -> Callable[[], None]:
        cid = normalize_channel_id(channel_id, session_id)
        sid = live_session_id(cid, session_id)
        if not cid:
            raise ValueError("proactive payload requires channel_id")
        connection = _Connection(
            session_id=sid,
            channel_id=cid,
            gen_id=gen_id,
            port=port,
            put_payload=put_payload,
        )
        with self._lock:
            self._connections[cid] = connection
            bus = self._outbound_bus
        if bus is not None:
            bus.on_connection_ready(sid, cid)

        def _unregister() -> None:
            with self._lock:
                if self._connections.get(cid) is connection:
                    self._connections.pop(cid, None)

        return _unregister

    def begin_client_turn(self, session_id: str) -> None:
        with self._lock:
            self._client_turns.add(session_id.strip())
            cid = normalize_channel_id("", session_id)
            if cid:
                self._client_turns.add(cid)
                self._client_turns.add(live_session_id(cid))

    def update_port(self, session_id: str, channel_id: str, port: Any) -> None:
        cid = normalize_channel_id(channel_id, session_id)
        with self._lock:
            connection = self._connections.get(cid)
            if connection is not None:
                connection.port = port

    def end_client_turn(self, session_id: str) -> None:
        sid = session_id.strip()
        cid = normalize_channel_id("", sid)
        with self._lock:
            self._client_turns.discard(sid)
            if cid:
                self._client_turns.discard(cid)
                self._client_turns.discard(live_session_id(cid))
            connection = self._connections.get(cid) if cid else None
            if connection is None:
                connection = next(
                    (
                        candidate
                        for candidate in self._connections.values()
                        if candidate.session_id == sid
                    ),
                    None,
                )
            payload = None
            if (
                connection is not None
                and not connection.server_turn_open
                and not connection.active_delivery_id
                and connection.queued_proactive
            ):
                payload = connection.queued_proactive.popleft()
        if connection is not None and payload is not None:
            self._deliver_proactive(connection, payload)
        if connection is not None and self._outbound_bus is not None:
            self._outbound_bus.on_connection_ready(
                connection.session_id,
                connection.channel_id,
            )

    def emit(self, session_id: str, event: SpeakStreamEvent) -> None:
        sid = session_id.strip()
        cid = normalize_channel_id("", sid)
        with self._lock:
            connections = [
                connection
                for connection in self._connections.values()
                if connection.session_id == sid or connection.channel_id == cid
            ]
            client_turn = (
                sid in self._client_turns
                or (cid in self._client_turns if cid else False)
            )
        for connection in connections:
            if client_turn:
                connection.port.emit(connection.session_id, event)
            else:
                self._emit_server_event(connection, event)

    def enqueue_proactive(self, payload: dict[str, Any]) -> bool:
        queued = dict(payload)
        raw_cid = str(queued.get("channel_id", "") or "").strip()
        if not raw_cid:
            raise ValueError("proactive payload requires channel_id")
        cid = normalize_channel_id(
            raw_cid,
            str(queued.get("session_id", "") or ""),
        )
        if not cid:
            raise ValueError("proactive payload requires channel_id")
        sid = live_session_id(cid, str(queued.get("session_id", "") or ""))
        queued["channel_id"] = cid
        queued["session_id"] = sid
        queued["delivery_id"] = str(
            queued.get("delivery_id")
            or queued.get("proactive_intent_id")
            or uuid.uuid4()
        )
        if not str(queued.get("created_at") or "").strip():
            from datetime import datetime, timezone

            queued["created_at"] = datetime.now(timezone.utc).isoformat()
        payload["delivery_id"] = queued["delivery_id"]
        payload["channel_id"] = cid
        payload["session_id"] = sid
        if queued.get("created_at"):
            payload["created_at"] = queued["created_at"]
        with self._lock:
            connection = self._connections.get(cid)
            if connection is None:
                return False
            if (
                connection.server_turn_open
                or connection.active_delivery_id
                or self._is_client_turn_locked(connection)
            ):
                connection.queued_proactive.append(dict(queued))
                return True
        queued["_requires_ack"] = True
        self._deliver_proactive(connection, queued)
        return True

    def pending_count(self, session_id: str, channel_id: str = "") -> int:
        cid = normalize_channel_id(channel_id, session_id)
        with self._lock:
            connection = self._connections.get(cid)
            if connection is None:
                return 0
            return len(connection.queued_proactive) + (
                1 if connection.active_delivery_id else 0
            )

    def pending_notifications(self, channel_id: str) -> list[dict[str, Any]]:
        """兼容旧 SSE 重放：转发 Bus 上仍待创建界面的请求。"""
        cid = normalize_channel_id(channel_id)
        bus = self._outbound_bus
        if bus is None:
            return []
        return list(bus.pending_proactive_notifications(cid))

    def acknowledge_proactive(
        self,
        session_id: str,
        channel_id: str,
        delivery_id: str,
    ) -> bool:
        cid = normalize_channel_id(channel_id, session_id)
        did = delivery_id.strip()
        with self._lock:
            connection = self._connections.get(cid)
            removed = False
            if connection is not None and connection.active_delivery_id == did:
                connection.active_delivery_id = ""
                removed = True
            if connection is not None:
                before = len(connection.queued_proactive)
                connection.queued_proactive = deque(
                    item
                    for item in connection.queued_proactive
                    if str(item.get("delivery_id", "")) != did
                )
                removed = removed or len(connection.queued_proactive) != before
            next_payload = (
                connection.queued_proactive.popleft()
                if connection is not None
                and not connection.server_turn_open
                and not connection.active_delivery_id
                and connection.queued_proactive
                else None
            )
        if next_payload is not None:
            next_payload["_requires_ack"] = True
            self._deliver_proactive(connection, next_payload)
        elif connection is not None and self._outbound_bus is not None:
            self._outbound_bus.on_connection_ready(connection.session_id, cid)
        return removed

    def has_connection(self, session_id: str, channel_id: str = "") -> bool:
        cid = normalize_channel_id(channel_id, session_id)
        sid = session_id.strip()
        with self._lock:
            if cid and cid in self._connections:
                return True
            return any(
                connection.session_id == sid
                for connection in self._connections.values()
            )

    def is_client_turn_active(self, session_id: str) -> bool:
        with self._lock:
            return self._is_client_turn_locked_sid(session_id.strip())

    def _is_client_turn_locked(self, connection: _Connection) -> bool:
        return self._is_client_turn_locked_sid(connection.session_id) or (
            connection.channel_id in self._client_turns
        )

    def _is_client_turn_locked_sid(self, session_id: str) -> bool:
        sid = session_id.strip()
        cid = normalize_channel_id("", sid)
        return sid in self._client_turns or (bool(cid) and cid in self._client_turns)

    def _deliver_proactive(
        self,
        connection: _Connection,
        payload: dict[str, Any],
    ) -> None:
        text = str(payload.get("message", "")).strip()
        if not text:
            return
        with self._lock:
            if (
                connection.server_turn_open
                or connection.active_delivery_id
                or self._is_client_turn_locked(connection)
            ):
                if not payload.get("_requires_ack"):
                    connection.queued_proactive.append(dict(payload))
                elif not any(
                    str(item.get("delivery_id", "")) == str(payload.get("delivery_id", ""))
                    for item in connection.queued_proactive
                ):
                    connection.queued_proactive.append(dict(payload))
                return
        meta = {
            "server_initiated": True,
            "proactive": True,
            "source": payload.get("source", "presence"),
            "proactive_intent_id": payload.get("proactive_intent_id", ""),
            "delivery_id": payload.get("delivery_id", ""),
            "agent_initiated": bool(payload.get("agent_initiated", True)),
        }
        created_at = str(payload.get("created_at") or "").strip()
        if created_at:
            meta["created_at"] = created_at
        if payload.get("_requires_ack"):
            connection.active_delivery_id = str(payload.get("delivery_id", ""))
        self._start_server_turn(connection, meta)
        speak_event = SpeakStreamEvent(kind="speak", text=text, meta=meta)
        connection.port.emit(connection.session_id, speak_event)
        connection.server_text.append(text)
        connection.server_events.append(
            {
                "kind": "speak",
                "text": text,
                "final": False,
                "meta": {**meta, "field": "speak"},
            }
        )
        self._finish_server_turn(
            connection,
            SpeakStreamEvent(kind="finish", text="", final=True, meta=meta),
        )

    def _emit_server_event(
        self,
        connection: _Connection,
        event: SpeakStreamEvent,
    ) -> None:
        self._start_server_turn(
            connection,
            {
                "server_initiated": True,
                "agent_initiated": True,
                "proactive": True,
                "source": str(event.meta.get("reason", "") or "session_social"),
            },
        )
        connection.port.emit(connection.session_id, event)
        if event.kind in (
            "thought",
            "speak",
            "action",
            "state",
            "finish",
            "observe",
            "outline",
            "anchor",
            "segment",
        ):
            connection.server_events.append(
                {
                    "kind": event.kind,
                    "text": event.text,
                    "final": bool(event.final),
                    "meta": dict(event.meta or {}),
                }
            )
        if event.kind == "speak" and event.text.strip():
            connection.server_text.append(event.text.strip())
        if event.kind == "finish" and event.final:
            self._finish_server_turn(connection, event, already_emitted=True)

    def _start_server_turn(
        self,
        connection: _Connection,
        meta: dict[str, Any],
    ) -> None:
        if connection.server_turn_open:
            return
        connection.server_turn_open = True
        connection.server_text.clear()
        connection.server_events.clear()
        connection.put_payload({
            "type": "turn_start",
            "gen_id": connection.gen_id,
            "session_id": connection.session_id,
            "question": "",
            **meta,
        })

    def _finish_server_turn(
        self,
        connection: _Connection,
        event: SpeakStreamEvent,
        *,
        already_emitted: bool = False,
    ) -> None:
        if not already_emitted:
            connection.port.emit(connection.session_id, event)
        answer = "\n".join(connection.server_text).strip()
        flush = getattr(connection.port, "flush_pending", None)
        if flush is None:
            self._complete_server_turn(connection, answer)
            return
        future = asyncio.run_coroutine_threadsafe(
            flush(connection.session_id),
            connection.port.loop,
        )
        future.add_done_callback(
            lambda _future: self._complete_server_turn(connection, answer),
        )

    def _complete_server_turn(self, connection: _Connection, answer: str) -> None:
        created_at = ""
        if connection.server_events:
            first_meta = connection.server_events[0].get("meta") or {}
            if isinstance(first_meta, dict):
                created_at = str(first_meta.get("created_at") or "").strip()
        payload = {
            "type": "turn_finish",
            "gen_id": connection.gen_id,
            "session_id": connection.session_id,
            "answer": answer,
            "server_initiated": True,
            "delivery_id": connection.active_delivery_id,
            "speak_events": list(connection.server_events),
        }
        if created_at:
            payload["created_at"] = created_at
        connection.put_payload(payload)
        with self._lock:
            connection.server_turn_open = False
            connection.server_text.clear()
            connection.server_events.clear()
            next_payload = None
            if connection.queued_proactive and not connection.active_delivery_id:
                next_payload = connection.queued_proactive.popleft()
                next_payload["_requires_ack"] = True
        if next_payload is not None:
            self._deliver_proactive(connection, next_payload)
