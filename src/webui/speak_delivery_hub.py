from __future__ import annotations

import asyncio
import threading
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable

from agent.soul.speak.io.outbound.notify import make_proactive_available_event
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
    queued_proactive: deque[dict[str, Any]] = field(default_factory=deque)
    active_delivery_id: str = ""


class WebUISpeakDeliveryHub:
    """Routes Soul Speak output to exact long-lived WebUI session connections."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._connections: dict[tuple[str, str], _Connection] = {}
        self._pending: dict[tuple[str, str], deque[dict[str, Any]]] = defaultdict(deque)
        self._client_turns: set[str] = set()

    def register(
        self,
        *,
        session_id: str,
        channel_id: str,
        gen_id: str,
        port: Any,
        put_payload: Callable[[dict[str, Any]], None],
    ) -> Callable[[], None]:
        sid = session_id.strip()
        cid = channel_id.strip() or sid
        key = (sid, cid)
        connection = _Connection(
            session_id=sid,
            channel_id=cid,
            gen_id=gen_id,
            port=port,
            put_payload=put_payload,
        )
        with self._lock:
            self._connections[key] = connection
            pending = self._pending.get(key)
            if not pending and cid:
                pending = self._pending.get((sid, ""))
            next_payload = dict(pending[0]) if pending else None
        if next_payload is not None:
            next_payload["_requires_ack"] = True
            self._deliver_proactive(connection, next_payload)

        def _unregister() -> None:
            with self._lock:
                if self._connections.get(key) is connection:
                    self._connections.pop(key, None)

        return _unregister

    def begin_client_turn(self, session_id: str) -> None:
        with self._lock:
            self._client_turns.add(session_id.strip())

    def update_port(self, session_id: str, channel_id: str, port: Any) -> None:
        key = (session_id.strip(), channel_id.strip() or session_id.strip())
        with self._lock:
            connection = self._connections.get(key)
            if connection is not None:
                connection.port = port

    def end_client_turn(self, session_id: str) -> None:
        sid = session_id.strip()
        with self._lock:
            self._client_turns.discard(sid)
            payloads: list[tuple[_Connection, dict[str, Any]]] = []
            for (registered_sid, channel_id), connection in self._connections.items():
                if (
                    registered_sid != sid
                    or connection.server_turn_open
                    or connection.active_delivery_id
                ):
                    continue
                pending = self._pending.get((sid, channel_id)) or self._pending.get(
                    (sid, ""),
                )
                if pending:
                    payload = dict(pending[0])
                    payload["_requires_ack"] = True
                    payloads.append((connection, payload))
                elif connection.queued_proactive:
                    payloads.append(
                        (connection, connection.queued_proactive.popleft()),
                    )
        for connection, payload in payloads:
            self._deliver_proactive(connection, payload)

    def emit(self, session_id: str, event: SpeakStreamEvent) -> None:
        sid = session_id.strip()
        with self._lock:
            connections = [
                connection
                for (registered_sid, _), connection in self._connections.items()
                if registered_sid == sid
            ]
            client_turn = sid in self._client_turns
        for connection in connections:
            if client_turn:
                connection.port.emit(sid, event)
            else:
                self._emit_server_event(connection, event)

    def enqueue_proactive(self, payload: dict[str, Any]) -> bool:
        queued = dict(payload)
        sid = str(queued.get("session_id", "")).strip()
        cid = str(queued.get("channel_id", "")).strip()
        if not sid:
            raise ValueError("proactive payload requires session_id")
        if not cid:
            raise ValueError("proactive payload requires channel_id")
        queued["delivery_id"] = str(
            queued.get("delivery_id")
            or queued.get("proactive_intent_id")
            or uuid.uuid4()
        )
        payload["delivery_id"] = queued["delivery_id"]
        key = (sid, cid)
        with self._lock:
            connection = self._connections.get(key)
            if connection is None and not cid:
                connection = next(
                    (
                        candidate
                        for (registered_sid, _), candidate in self._connections.items()
                        if registered_sid == sid
                    ),
                    None,
                )
            self._pending[key].append(queued)
            if connection is None:
                return False
        queued["_requires_ack"] = True
        self._deliver_proactive(connection, queued)
        return True

    def pending_count(self, session_id: str, channel_id: str = "") -> int:
        sid = session_id.strip()
        cid = channel_id.strip()
        with self._lock:
            return len(self._pending.get((sid, cid), ()))

    def pending_notifications(self, channel_id: str) -> list[dict[str, Any]]:
        cid = channel_id.strip()
        notifications: list[dict[str, Any]] = []
        with self._lock:
            for (session_id, pending_channel), payloads in self._pending.items():
                if pending_channel and pending_channel != cid:
                    continue
                if not payloads:
                    continue
                payload = payloads[0]
                notifications.append(
                    make_proactive_available_event(
                        session_id=session_id,
                        channel_id=pending_channel,
                        proactive_intent_id=str(payload.get("proactive_intent_id", "") or ""),
                        delivery_id=str(payload.get("delivery_id", "") or ""),
                        source=str(payload.get("source", "") or ""),
                        wait_reply=bool(payload.get("wait_reply", False)),
                        online=False,
                    )
                )
        return notifications

    def acknowledge_proactive(
        self,
        session_id: str,
        channel_id: str,
        delivery_id: str,
    ) -> bool:
        sid = session_id.strip()
        cid = channel_id.strip() or sid
        did = delivery_id.strip()
        with self._lock:
            removed = False
            for key in ((sid, cid), (sid, "")):
                pending = self._pending.get(key)
                if pending is None:
                    continue
                retained = deque(
                    payload
                    for payload in pending
                    if str(payload.get("delivery_id", "")) != did
                )
                removed = removed or len(retained) != len(pending)
                if retained:
                    self._pending[key] = retained
                else:
                    self._pending.pop(key, None)
            key = (sid, cid)
            connection = self._connections.get(key)
            if connection is not None and connection.active_delivery_id == did:
                connection.active_delivery_id = ""
            next_pending = self._pending.get(key) or self._pending.get((sid, ""))
            next_payload = (
                dict(next_pending[0])
                if connection is not None
                and not connection.server_turn_open
                and not connection.active_delivery_id
                and next_pending
                else None
            )
            queued_payload = (
                connection.queued_proactive.popleft()
                if connection is not None
                and next_payload is None
                and not connection.server_turn_open
                and not connection.active_delivery_id
                and connection.queued_proactive
                else None
            )
        if next_payload is not None:
            next_payload["_requires_ack"] = True
            self._deliver_proactive(connection, next_payload)
        elif queued_payload is not None:
            self._deliver_proactive(connection, queued_payload)
        return removed

    def has_connection(self, session_id: str) -> bool:
        sid = session_id.strip()
        with self._lock:
            return any(
                registered_sid == sid
                for registered_sid, _ in self._connections
            )

    def is_client_turn_active(self, session_id: str) -> bool:
        with self._lock:
            return session_id.strip() in self._client_turns

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
                or connection.session_id in self._client_turns
            ):
                if not payload.get("_requires_ack"):
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
        if payload.get("_requires_ack"):
            connection.active_delivery_id = str(payload.get("delivery_id", ""))
        self._start_server_turn(connection, meta)
        connection.port.emit(
            connection.session_id,
            SpeakStreamEvent(kind="speak", text=text, meta=meta),
        )
        connection.server_text.append(text)
        self._finish_server_turn(
            connection,
            SpeakStreamEvent(kind="finish", text=text, final=True, meta=meta),
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
        connection.put_payload({
            "type": "turn_finish",
            "gen_id": connection.gen_id,
            "session_id": connection.session_id,
            "answer": answer,
            "server_initiated": True,
            "delivery_id": connection.active_delivery_id,
        })
        with self._lock:
            connection.server_turn_open = False
            connection.server_text.clear()
            pending = self._pending.get(
                (connection.session_id, connection.channel_id),
            ) or self._pending.get((connection.session_id, ""))
            next_payload = None
            if pending and not connection.active_delivery_id:
                next_payload = dict(pending[0])
                next_payload["_requires_ack"] = True
            elif connection.queued_proactive and not connection.active_delivery_id:
                next_payload = connection.queued_proactive.popleft()
        if next_payload is not None:
            self._deliver_proactive(connection, next_payload)
