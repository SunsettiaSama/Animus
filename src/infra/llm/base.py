from __future__ import annotations

import subprocess
import sys
import threading
import time
from abc import abstractmethod
from collections import deque
from pathlib import Path
from typing import Literal

from config.llm_core.vllm_config import VLLMConfig
from infra.llm.backend import BaseInferenceBackend

VLLM_LINUX_ONLY = (
    "vLLM requires a Linux environment. "
    "On Windows, install WSL2 (ubuntu-24.04+) to enable this backend. "
    "Falling back to backend='transformers'."
)

# ── WSL2 helpers (Windows-only) ───────────────────────────────────────────────

def _wsl2_available() -> bool:
    """Return True if WSL2 is installed and a distro responds on this machine."""
    if sys.platform != "win32":
        return False
    import shutil
    if shutil.which("wsl") is None:
        return False
    try:
        r = subprocess.run(
            ["wsl", "echo", "ok"],
            capture_output=True,
            timeout=8,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _win_to_wsl_path(path: str) -> str:
    """Convert a Windows absolute path to /mnt/<drive>/... (WSL UNC format)."""
    p = path.replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        drive = p[0].lower()
        rest  = p[2:]          # already starts with '/'
        return f"/mnt/{drive}{rest}"
    return p


def _build_wsl_cmd(cmd: list[str]) -> list[str]:
    """Wrap a Windows Python subprocess command for execution inside WSL2.

    - Replaces the Windows ``sys.executable`` with ``python3``.
    - Converts any Windows absolute paths (``X:\\...``) in the argument list
      to their ``/mnt/x/...`` WSL equivalents.
    - Prepends ``wsl -- env PYTHONPATH=<src>`` so project modules are found.
    """
    # src/ directory: base.py lives at src/infra/llm/base.py → 3 parents up
    src_dir  = str(Path(__file__).resolve().parent.parent.parent)
    wsl_src  = _win_to_wsl_path(src_dir)

    wsl_args: list[str] = []
    for arg in cmd:
        if arg == sys.executable:
            wsl_args.append("python3")
        elif (
            len(arg) >= 2
            and arg[1] == ":"
            and (arg[0].isalpha())
        ):
            wsl_args.append(_win_to_wsl_path(arg))
        else:
            wsl_args.append(arg)

    return ["wsl", "--", "env", f"PYTHONPATH={wsl_src}"] + wsl_args


class BaseVLLMManager(BaseInferenceBackend):
    """Abstract base for all vLLM server managers.

    Encapsulates the shared lifecycle infrastructure used by every
    concrete vLLM provider:

    - Thread-safe state machine (stopped / starting / running / error)
    - Subprocess handle and graceful shutdown
    - Log ring-buffer captured from stdout/stderr via a daemon thread
    - Background health-watch thread that promotes "starting" → "running"
    - TCP port probe and HTTP health endpoint check

    Concrete subclasses must implement:

    - ``start(model, cfg)``  — launch the server process
    - ``stop()``             — terminate it
    - ``status()``           — return a state dict (include ``"provider"`` key)
    - ``base_url``           — property returning the OpenAI-compat base URL
    - ``health_check()``     — full HTTP health probe
    - ``build_llm(cfg)``     — return the LLM instance pointed at this server
    - ``provider``           — string identifier for this backend

    Shared helpers available to subclasses:

    - ``_launch_subprocess(cmd)``       — spawn a Popen, attach log/health threads
    - ``_stop_process()``               — graceful terminate → kill
    - ``_port_is_open()``              — non-raising TCP probe
    - ``get_logs(n)``                   — return last n lines from ring-buffer
    """

    _LOG_MAXLEN: int = 500
    _LOG_TAG:    str = "vllm"

    def __init__(self) -> None:
        self._state: Literal["stopped", "starting", "running", "error"] = "stopped"
        self._process: subprocess.Popen | None = None
        self._cfg: VLLMConfig | None = None
        self._model: str = ""
        self._log_lines: deque[str] = deque(maxlen=self._LOG_MAXLEN)
        self._lock = threading.Lock()

    # ── Abstract interface ────────────────────────────────────────────────────

    @abstractmethod
    def start(self, model: str, cfg: VLLMConfig) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def status(self) -> dict:
        raise NotImplementedError

    @property
    @abstractmethod
    def base_url(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> bool:
        raise NotImplementedError

    # ── Shared helpers for subclasses ─────────────────────────────────────────

    def _launch_subprocess(self, cmd: list[str]) -> None:
        """Spawn *cmd* as a subprocess and start log-capture / health-watch threads.

        On Windows, attempts to route the command through WSL2.  Raises
        RuntimeError only if WSL2 is also unavailable.
        """
        if sys.platform == "win32":
            if not _wsl2_available():
                raise RuntimeError(VLLM_LINUX_ONLY)
            cmd = _build_wsl_cmd(cmd)

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

        tag = self._LOG_TAG
        threading.Thread(
            target=self._capture_logs,
            args=(process,),
            daemon=True,
            name=f"{tag}-log-capture",
        ).start()
        threading.Thread(
            target=self._watch_health,
            args=(self._cfg,),
            daemon=True,
            name=f"{tag}-health-watch",
        ).start()

    def _stop_process(self) -> None:
        """Grab the process handle, signal stopped, then terminate → kill."""
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

    # ── Internal daemon threads ───────────────────────────────────────────────

    def _capture_logs(self, process: subprocess.Popen) -> None:
        tag = self._LOG_TAG
        for line in process.stdout:
            stripped = line.rstrip("\n")
            with self._lock:
                self._log_lines.append(stripped)
            print(f"[{tag}] {stripped}", file=sys.stderr, flush=True)

        with self._lock:
            if self._state not in ("stopped",):
                self._state = "error"

    def _watch_health(self, cfg: VLLMConfig | None) -> None:
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
