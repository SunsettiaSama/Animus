"""Speak WebSocket client — same protocol as WebUI SpeakSession."""

from __future__ import annotations

import json
import threading
import uuid
from collections import deque
from typing import Any, Callable

import websocket

DEFAULT_URL = "ws://127.0.0.1:8300/ws/speak/run"
DEFAULT_CHANNEL_ID = "pygame-town"


class SpeakWsClient:
    """Background-thread Speak WS; main thread drains via poll()."""

    def __init__(
        self,
        *,
        url: str = DEFAULT_URL,
        session_id: str | None = None,
        channel_id: str = DEFAULT_CHANNEL_ID,
        gen_id: str | None = None,
        delivery_mode: str = "stream",
        pipeline: str = "request_driven",
    ) -> None:
        self.url = url
        self.session_id = session_id or f"pygame-town-{uuid.uuid4().hex[:12]}"
        self.channel_id = channel_id
        self.gen_id = gen_id or uuid.uuid4().hex
        self.delivery_mode = "simulated" if delivery_mode == "simulated" else "stream"
        self.pipeline = pipeline or "request_driven"

        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._inbox: deque[dict[str, Any]] = deque()
        self._connected = False
        self._session_ready = threading.Event()
        self._closed = False

    def _payload(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "gen_id": self.gen_id,
            "session_id": self.session_id,
            "channel_id": self.channel_id,
            "delivery_mode": self.delivery_mode,
            "pipeline": self.pipeline,
        }
        if extra:
            body.update(extra)
        return body

    def _enqueue(self, msg: dict[str, Any]) -> None:
        with self._lock:
            self._inbox.append(msg)

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        self._connected = True
        ws.send(json.dumps(self._payload({"type": "session_open"})))

    def _on_message(self, _ws: websocket.WebSocketApp, raw: str) -> None:
        msg = json.loads(raw)
        if not isinstance(msg, dict):
            raise RuntimeError(f"Speak frame must be object, got {type(msg)!r}")
        msg_type = str(msg.get("type", ""))
        if msg_type == "session_ready":
            self._session_ready.set()
        if msg_type == "error":
            self._enqueue(msg)
            return
        gen = str(msg.get("gen_id", "")).strip()
        if gen and gen != self.gen_id and not msg_type.startswith("work_"):
            return
        self._enqueue(msg)

    def _on_error(self, _ws: websocket.WebSocketApp, error: Any) -> None:
        self._enqueue({"type": "error", "message": str(error)})

    def _on_close(self, _ws: websocket.WebSocketApp, _code: Any, _msg: Any) -> None:
        self._connected = False
        self._enqueue({"type": "disconnected"})

    def connect(self, *, timeout_s: float = 15.0) -> None:
        if self._connected and self._session_ready.is_set():
            return
        self._closed = False
        self._session_ready.clear()
        self._ws = websocket.WebSocketApp(
            self.url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._thread = threading.Thread(
            target=self._ws.run_forever,
            name="speak-ws-client",
            daemon=True,
        )
        self._thread.start()
        if not self._session_ready.wait(timeout_s):
            raise TimeoutError(f"Speak session_ready timeout after {timeout_s}s ({self.url})")

    def is_connected(self) -> bool:
        return self._connected and self._ws is not None

    def poll(self) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._inbox)
            self._inbox.clear()
        return items

    def send_user_message(self, question: str) -> bool:
        text = str(question).strip()
        if not text or not self.is_connected() or self._ws is None:
            return False
        self._ws.send(json.dumps(self._payload({"type": "user_message", "question": text})))
        return True

    def acknowledge_proactive(self, delivery_id: str) -> bool:
        did = str(delivery_id).strip()
        if not did or not self.is_connected() or self._ws is None:
            return False
        self._ws.send(json.dumps(self._payload({"type": "proactive_ack", "delivery_id": did})))
        return True

    def close(self) -> None:
        self._closed = True
        if self._ws is not None and self._connected:
            self._ws.send(json.dumps(self._payload({"type": "close"})))
            self._ws.close()
        self._connected = False


def drain_until(
    client: SpeakWsClient,
    predicate: Callable[[dict[str, Any]], bool],
    *,
    timeout_s: float = 60.0,
    sleep_s: float = 0.05,
) -> dict[str, Any]:
    """Blocking helper for scripts/tests; game loop should use poll() instead."""
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for msg in client.poll():
            if predicate(msg):
                return msg
            if msg.get("type") == "error":
                raise RuntimeError(str(msg.get("message") or "Speak error"))
        time.sleep(sleep_s)
    raise TimeoutError("SpeakWsClient.drain_until timed out")
