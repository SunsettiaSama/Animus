from __future__ import annotations

import dataclasses
import sys
import urllib.request

from config.llm_core.config import LLMConfig
from config.llm_core.vllm_config import VLLMConfig
from infra.llm.base import BaseVLLMManager
from infra.llm.llm import BaseLLM, OpenAILLM


class CustomVLLMManager(BaseVLLMManager):
    """Manages the lifecycle of the custom (reproduced) vLLM server.

    This is the insertion point for the vllm-clone implementation.
    Override ``_build_cmd`` in a subclass (or directly here) to return
    the shell command that launches the custom inference server::

        def _build_cmd(self, model, cfg):
            return [
                sys.executable, "-m", "my_vllm.server",
                "--model", model,
                "--host", cfg.host,
                "--port", str(cfg.port),
            ]

    Until ``_build_cmd`` is implemented it returns ``None``, which causes
    ``start()`` to transition immediately to the ``"error"`` state and emit
    a descriptive log entry.
    """

    _LOG_TAG = "vllm-clone"

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self, model: str, cfg: VLLMConfig) -> None:
        with self._lock:
            if self._state in ("starting", "running"):
                return
            self._state = "starting"
            self._model = model
            self._cfg = cfg
            self._log_lines.clear()

        cmd = self._build_cmd(model, cfg)
        if cmd is None:
            msg = (
                "[vllm-clone] No serving command defined. "
                "Implement CustomVLLMManager._build_cmd() to provide "
                "the custom vLLM server entrypoint."
            )
            print(msg, file=sys.stderr, flush=True)
            with self._lock:
                self._log_lines.append(msg)
                self._state = "error"
            return

        self._launch_subprocess(cmd)

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
            "provider": self.provider,
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

    # ── BaseInferenceBackend interface ────────────────────────────────────────

    def build_llm(self, cfg: LLMConfig) -> BaseLLM:
        return OpenAILLM(dataclasses.replace(cfg, base_url=self.base_url))

    @property
    def provider(self) -> str:
        return "vllm-clone"

    # ── Extension point ───────────────────────────────────────────────────────

    def _build_cmd(self, model: str, cfg: VLLMConfig) -> list[str] | None:
        """Return the command list that starts the custom server, or ``None``.

        Returning ``None`` (the default) signals "not yet implemented" and
        transitions the manager to the ``"error"`` state with a log message.
        """
        return None
