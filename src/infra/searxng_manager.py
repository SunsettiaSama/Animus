from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Literal

from infra.base_service import BaseServiceManager


class SearXNGManager(BaseServiceManager):
    """Manages the SearXNG Docker container lifecycle.

    Migrated from ``src/run.py`` ``ensure_searxng`` and related helpers so
    the same logic is available both from the CLI launcher and from the
    WebUI ``/api/services/searxng/*`` endpoints.

    Usage::

        mgr = SearXNGManager(
            container_name="react-searxng",
            image="searxng/searxng",
            host_port=8888,
            container_port=8080,
            settings_yml=Path("config/network/searxng/settings.yml"),
        )
        mgr.start()
        print(mgr.status())
        mgr.stop()
    """

    def __init__(
        self,
        container_name: str = "react-searxng",
        image: str = "searxng/searxng",
        host_port: int = 8888,
        container_port: int = 8080,
        settings_yml: Path | None = None,
    ) -> None:
        self._container_name = container_name
        self._image = image
        self._host_port = host_port
        self._container_port = container_port
        self._settings_yml = settings_yml

    # ── BaseServiceManager interface ──────────────────────────────────────────

    def start(self, **kwargs) -> None:
        if not self._docker_available():
            return
        raw = self._container_status()
        if raw.startswith("Up"):
            return
        if raw:
            self._run_docker("start", self._container_name, timeout=15)
        else:
            cmd = [
                "run", "-d",
                "--name",    self._container_name,
                "--restart", "unless-stopped",
                "-p",        f"127.0.0.1:{self._host_port}:{self._container_port}",
            ]
            if self._settings_yml and self._settings_yml.exists():
                cmd += ["-v", f"{self._settings_yml}:/etc/searxng/settings.yml"]
            cmd.append(self._image)
            self._run_docker(*cmd, timeout=120)

    def stop(self) -> None:
        if not self._docker_available():
            return
        raw = self._container_status()
        if raw.startswith("Up"):
            self._run_docker("stop", self._container_name, timeout=20)

    def status(self) -> dict:
        if not self._docker_available():
            return {"state": "unavailable", "detail": "Docker daemon not available"}
        raw = self._container_status()
        if raw.startswith("Up"):
            state: Literal["stopped", "starting", "running", "error"] = "running"
        elif raw:
            state = "stopped"
        else:
            state = "stopped"
        return {
            "state":   state,
            "url":     f"http://127.0.0.1:{self._host_port}",
            "healthy": self._port_is_open() if state == "running" else False,
            "container": self._container_name,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _run_docker(self, *args: str, timeout: int = 10) -> subprocess.CompletedProcess | None:
        import shutil
        if shutil.which("docker") is None:
            return None
        try:
            return subprocess.run(
                ["docker", *args],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None

    def _docker_available(self) -> bool:
        import shutil
        import time as _time
        # Cache availability for 30 s to avoid hammering `docker info`.
        now = _time.monotonic()
        if hasattr(self, '_docker_cache_until') and now < self._docker_cache_until:
            return self._docker_cache_value  # type: ignore[attr-defined]
        if shutil.which("docker") is None:
            self._docker_cache_value = False
            self._docker_cache_until = now + 30
            return False
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            available = result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            available = False
        self._docker_cache_value = available
        self._docker_cache_until = now + 30
        return available

    def _container_status(self) -> str:
        result = self._run_docker(
            "ps", "-a",
            "--filter", f"name=^{self._container_name}$",
            "--format", "{{.Status}}",
        )
        return result.stdout.strip() if result else ""

    def _port_is_open(self) -> bool:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        rc = sock.connect_ex(("127.0.0.1", self._host_port))
        sock.close()
        return rc == 0

    def wait_until_up(self, seconds: int = 12) -> bool:
        for _ in range(seconds):
            time.sleep(1)
            if self._container_status().startswith("Up"):
                return True
        return False

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._host_port}"
