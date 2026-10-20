# -*- coding: utf-8 -*-
"""《星陨之痕》桥：node 无头 harness 子进程管理 + NDJSON 双向协议。

stdout（harness → python）：event / scene / npc_wait / log / done
stdin（python → harness）：npc_line（soul 台词回注游戏）
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEMO_DIR = _REPO_ROOT / "demos" / "metroidvania"
HARNESS = "perception/harness.js"


def node_available() -> bool:
    return shutil.which("node") is not None


def demo_available() -> bool:
    return (DEMO_DIR / HARNESS).exists()


class MetroidvaniaBridge:
    """《星陨之痕》无头游戏桥。"""

    def __init__(self, *, scenario: str = "story", cwd: str | Path | None = None) -> None:
        self._scenario = scenario
        self._cwd = Path(cwd) if cwd is not None else DEMO_DIR
        self._proc: subprocess.Popen[str] | None = None

    # ── 生命周期 ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._proc is not None:
            return
        if not node_available():
            raise RuntimeError("未找到 node（无头 harness 需要 Node.js 运行时）")
        harness = self._cwd / HARNESS
        if not harness.exists():
            raise RuntimeError(f"harness 不存在：{harness}")
        self._proc = subprocess.Popen(
            ["node", str(harness), "--scenario", self._scenario],
            cwd=str(self._cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        logger.info("[星陨之痕桥] harness 已启动 pid=%s scenario=%s", self._proc.pid, self._scenario)

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stop(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.poll() is None:
                self._proc.stdin.close() if self._proc.stdin else None
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.terminate()
                    self._proc.wait(timeout=5)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[星陨之痕桥] 停止异常：%s", exc)
        finally:
            self._proc = None

    def __enter__(self) -> MetroidvaniaBridge:
        self.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self.stop()

    # ── 协议读写 ─────────────────────────────────────────────────────────────

    def messages(self) -> Iterator[dict[str, Any]]:
        """迭代 harness 的 NDJSON 输出（阻塞直至 done/进程结束）。"""
        if self._proc is None or self._proc.stdout is None:
            raise RuntimeError("桥未启动")
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("[星陨之痕桥] 无法解析输出行：%s", line[:120])
                continue
            if msg.get("type") == "log":
                logger.info("[harness] %s", msg.get("text", ""))
                continue
            yield msg

    def send(self, msg: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("桥未启动")
        self._proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def send_npc_line(self, name: str, text: str, *, mode: str = "popup") -> None:
        """soul 台词回注游戏（popup=对话弹窗 / toast=角落短消息）。"""
        self.send({"type": "npc_line", "name": name, "text": text, "mode": mode})
