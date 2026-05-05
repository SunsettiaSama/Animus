from __future__ import annotations

import subprocess
import sys
import threading
import time
from collections import deque
from typing import Literal

from config.llm_core.vllm_config import VLLMConfig
from infra.base_service import BaseServiceManager


class VLLMServerManager(BaseServiceManager):
    """Manages the lifecycle of a vLLM server subprocess.

    The server is launched via ``vllm serve`` and exposes an OpenAI-compatible
    API.  A dedicated daemon thread captures stdout/stderr into a fixed-size
    ring buffer so callers can retrieve recent log lines without blocking.

    State machine::

        stopped ──start()──► starting ──healthy──► running
                                  └──error──► error
        running ──stop()───► stopped
        error   ──start()──► starting  (retry)

    Usage::

        mgr = VLLMServerManager()
        mgr.start("Qwen/Qwen2.5-7B-Instruct", VLLMConfig(tensor_parallel_size=2))
        # poll mgr.health_check() until True
        llm = OpenAILLM(base_url=mgr.base_url, api_key="EMPTY", ...)
        ...
        mgr.stop()
    """

    _LOG_MAXLEN = 500

    def __init__(self) -> None:
        self._state: Literal["stopped", "starting", "running", "error"] = "stopped"
        self._process: subprocess.Popen | None = None
        self._cfg: VLLMConfig | None = None
        self._model: str = ""
        self._log_lines: deque[str] = deque(maxlen=self._LOG_MAXLEN)
        self._lock = threading.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self, model: str, cfg: VLLMConfig) -> None:
        with self._lock:
            if self._state in ("starting", "running"):
                return
            self._state = "starting"
            self._model = model
            self._cfg = cfg
            self._log_lines.clear()

        cmd = cfg.to_cli_args(model)
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        with self._lock:
            self._process = process

        threading.Thread(
            target=self._capture_logs,
            args=(process,),
            daemon=True,
            name="vllm-log-capture",
        ).start()

        threading.Thread(
            target=self._watch_health,
            args=(cfg,),
            daemon=True,
            name="vllm-health-watch",
        ).start()

    def stop(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            self._state = "stopped"

        if process is None:
            return

        process.terminate()
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return
            time.sleep(0.2)
        process.kill()

    # ── Status / health ───────────────────────────────────────────────────────

    def status(self) -> dict:
        with self._lock:
            state = self._state
            pid = self._process.pid if self._process else None
        return {
            "state":    state,
            "pid":      pid,
            "base_url": self.base_url,
            "healthy":  self._port_is_open() if state == "running" else False,
        }

    def health_check(self) -> bool:
        """Full HTTP health check against the vLLM /health endpoint.

        Returns True on HTTP 200.  May raise on network errors — callers that
        poll during startup should use ``_port_is_open`` instead.
        """
        import urllib.request
        cfg = self._cfg
        if cfg is None:
            return False
        url = f"http://{cfg.host}:{cfg.port}/health"
        result = urllib.request.urlopen(urllib.request.Request(url), timeout=2)
        return result.status == 200

    def _port_is_open(self) -> bool:
        """Non-raising TCP probe — returns False if the port is not reachable."""
        import socket
        cfg = self._cfg
        if cfg is None:
            return False
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        rc = sock.connect_ex((cfg.host, cfg.port))
        sock.close()
        return rc == 0

    def get_logs(self, n: int = 100) -> list[str]:
        with self._lock:
            lines = list(self._log_lines)
        return lines[-n:]

    @property
    def base_url(self) -> str:
        cfg = self._cfg
        if cfg is None:
            return "http://127.0.0.1:8000/v1"
        return f"http://{cfg.host}:{cfg.port}/v1"

    # ── Internal threads ──────────────────────────────────────────────────────

    def _capture_logs(self, process: subprocess.Popen) -> None:
        for line in process.stdout:
            stripped = line.rstrip("\n")
            with self._lock:
                self._log_lines.append(stripped)
            print(f"[vllm] {stripped}", file=sys.stderr, flush=True)

        with self._lock:
            if self._state not in ("stopped",):
                self._state = "error"

    def _watch_health(self, cfg: VLLMConfig) -> None:
        deadline = time.monotonic() + 120.0
        while time.monotonic() < deadline:
            with self._lock:
                state = self._state
            if state not in ("starting",):
                return
            if self._port_is_open():
                with self._lock:
                    if self._state == "starting":
                        self._state = "running"
                return
            time.sleep(2.0)

        with self._lock:
            if self._state == "starting":
                self._state = "error"
