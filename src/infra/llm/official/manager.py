from __future__ import annotations

import urllib.request

from config.llm_core.vllm_config import VLLMConfig
from infra.llm.base import BaseVLLMManager


class OfficialVLLMManager(BaseVLLMManager):
    """Manages the official vLLM server subprocess (``vllm serve``).

    Launches the process using the CLI arguments produced by
    ``VLLMConfig.to_cli_args`` and exposes an OpenAI-compatible API.

    Usage::

        mgr = OfficialVLLMManager()
        mgr.start("Qwen/Qwen2.5-7B-Instruct", VLLMConfig(tensor_parallel_size=2))
        # poll mgr.health_check() or mgr.status()["state"] == "running"
        llm = OpenAILLM(base_url=mgr.base_url, api_key="EMPTY", ...)
        ...
        mgr.stop()
    """

    _LOG_TAG = "vllm"

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self, model: str, cfg: VLLMConfig) -> None:
        with self._lock:
            if self._state in ("starting", "running"):
                return
            self._state = "starting"
            self._model = model
            self._cfg = cfg
            self._log_lines.clear()

        self._launch_subprocess(cfg.to_cli_args(model))

    def stop(self) -> None:
        self._stop_process()

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
            "provider": "official",
        }

    @property
    def base_url(self) -> str:
        cfg = self._cfg
        if cfg is None:
            return "http://127.0.0.1:8000/v1"
        return f"http://{cfg.host}:{cfg.port}/v1"

    def health_check(self) -> bool:
        cfg = self._cfg
        if cfg is None:
            return False
        url = f"http://{cfg.host}:{cfg.port}/health"
        result = urllib.request.urlopen(urllib.request.Request(url), timeout=2)
        return result.status == 200
