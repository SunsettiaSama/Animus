"""soul_link — 桌宠与 Soul/Speak 的接线层。

复用 pygame_town 的 SpeakWsClient（/ws/speak/run，与 WebUI 同协议）：
- session 固定为 live:desktop-pet（与 WebUI 的 live:<channelId> 生命线约定一致）
- simulated 投递：soul 侧产出整块 speak + agent_typing 节奏，气泡观感自然
- typing pulse：用户在输入框打字时上报草稿（soul 能感知"对方正在打字"并停轮询）
- proactive：server_initiated turn → 气泡；展示完毕 ack，让 soul 继续下一条
- 断线自动重连（5s）
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from client.speak_ws import SpeakWsClient  # noqa: E402


def _meta(msg: dict) -> dict:
    meta = msg.get("meta")
    return meta if isinstance(meta, dict) else {}


class SoulLink:
    """把 Speak WS 帧翻译为气泡层/桌宠姿态回调。"""

    def __init__(
        self,
        bubbles,
        pet,
        *,
        channel_id: str = "desktop-pet",
        session_id: str = "live:desktop-pet",
        on_status=None,
    ) -> None:
        self.bubbles = bubbles
        self.pet = pet
        self.on_status = on_status or (lambda s: None)
        self.channel_id = channel_id
        self.session_id = session_id

        self._client = SpeakWsClient(
            url="ws://127.0.0.1:8300/ws/speak/run",
            session_id=session_id,
            channel_id=channel_id,
            delivery_mode="simulated",
            pipeline="request_driven",
        )
        self._pending_delivery_id = ""
        self._turn_proactive = False
        self._reconnect_at = 0.0

    # ── 生命周期 ───────────────────────────────────────────────────────────

    def start(self) -> None:
        self._client.connect(timeout_s=None)  # 不阻塞：主循环轮询状态

    def is_ready(self) -> bool:
        return self._client.is_ready()

    def tick(self) -> None:
        """主循环每帧调用：消费 WS 帧 + 断线重连。"""
        now = time.monotonic()
        if not self._client.is_connected():
            if now >= self._reconnect_at:
                self.on_status("connecting")
                try:
                    self._client.connect(timeout_s=None)
                    self._reconnect_at = now + 5.0
                except Exception:
                    self._reconnect_at = now + 5.0
            return

        for msg in self._client.poll():
            self._handle(msg)

    def close(self) -> None:
        self._client.close()

    # ── 出站 ───────────────────────────────────────────────────────────────

    def send_user_message(self, text: str) -> bool:
        return self._client.send_user_message(text)

    def send_typing_pulse(self, draft: str) -> None:
        """打字感知：soul 会暂停 poll 阶梯、读取 draft（当前实现仅记录不反应）。"""
        if not self._client.is_ready() or self._client._ws is None:
            return
        import json

        self._client._ws.send(json.dumps(self._client._payload({
            "type": "typing_pulse",
            "typing": bool(draft.strip()),
            "draft": draft,
        })))

    # ── 入站帧处理 ─────────────────────────────────────────────────────────

    def _handle(self, msg: dict) -> None:
        mtype = str(msg.get("type", ""))
        meta = _meta(msg)

        if mtype == "error":
            self.on_status(f"error: {str(msg.get('message', ''))[:60]}")
            return
        if mtype == "disconnected":
            self.on_status("reconnecting")
            self._reconnect_at = time.monotonic() + 5.0
            return

        if mtype == "turn_start":
            self._turn_proactive = self._is_proactive(msg, meta)
            self._pending_delivery_id = self._delivery_id(msg, meta)
            self.bubbles.begin_turn(proactive=self._turn_proactive)
            if self._turn_proactive:
                self.pet.show_emote("💬", 2.5)
            return

        if mtype == "speak_event":
            kind = str(msg.get("kind", ""))
            text = str(msg.get("text", "") or "")
            if kind == "speak":
                if text.strip():
                    self.bubbles.append_speak(text)
            elif kind in ("observe", "outline"):
                if text.strip():
                    self.bubbles.append_narrative(text)
            elif kind == "agent_typing":
                active = meta.get("active", True)
                self.bubbles.set_typing(str(active).lower() not in ("false", "0"))
            elif kind in ("silence", "state") and ("silence" in text.lower() or "silence" in kind):
                self.bubbles.note_silence()
                self.pet.close_eyes(2.0)
            elif kind == "action" and "wait" in text.lower():
                self.pet.close_eyes(min(4.0, self._wait_seconds(text)))
            return

        if mtype == "turn_finish":
            answer = str(msg.get("answer", "") or "")
            self.bubbles.end_turn(answer)
            if not answer.strip() and not self._turn_proactive:
                self.pet.show_emote("…", 1.2)   # 沉默也是表达
            self._ack_if_needed()
            self._turn_proactive = False
            return

        if mtype == "session_end":
            self.on_status("session_end")
            self._reconnect_at = time.monotonic() + 5.0

    # ── 工具 ───────────────────────────────────────────────────────────────

    @staticmethod
    def _is_proactive(msg: dict, meta: dict) -> bool:
        if bool(msg.get("server_initiated")) or bool(meta.get("server_initiated")):
            return True
        if str(msg.get("question", "")) == "" and bool(meta.get("proactive")):
            return True
        return bool(meta.get("agent_initiated"))

    @staticmethod
    def _delivery_id(msg: dict, meta: dict) -> str:
        did = str(msg.get("delivery_id", "") or "").strip()
        if not did:
            did = str(meta.get("delivery_id", "") or "").strip()
        return did

    @staticmethod
    def _wait_seconds(text: str) -> float:
        digits = "".join(ch if ch.isdigit() or ch == "." else " " for ch in text).split()
        try:
            return max(0.5, min(6.0, float(digits[0]) if digits else 1.5))
        except ValueError:
            return 1.5

    def _ack_if_needed(self) -> None:
        did = self._pending_delivery_id
        if did:
            self._client.acknowledge_proactive(did)
            self._pending_delivery_id = ""
