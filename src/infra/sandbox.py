from __future__ import annotations

import contextlib
import io
import os
import threading
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from config.infra.sandbox_config import SandboxConfig
from infra.base_service import BaseServiceManager


class SandboxManager(BaseServiceManager):
    """
    Agent 操作沙箱，提供三类隔离能力：
    - 文件系统路径验证（防止路径穿越，限制在 workspace_root 内）
    - Python 代码受限执行（黑名单模块过滤 + 超时 + stdout 捕获）
    - HTTP 域名访问策略（防 SSRF，支持白/黑名单）

    作为 BaseServiceManager 注册到 ServiceRegistry，与 VLLMServerManager /
    SearXNGManager 保持一致的基础设施接口。
    """

    def __init__(self, cfg: SandboxConfig | None = None) -> None:
        self._cfg = cfg or SandboxConfig()
        self._state: Literal["stopped", "running"] = "stopped"
        self._lock = threading.Lock()

    @property
    def cfg(self) -> SandboxConfig:
        return self._cfg

    # ── BaseServiceManager interface ──────────────────────────────────────────

    def start(self, **kwargs) -> None:
        workspace = Path(self._cfg.workspace_root)
        workspace.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._state = "running"

    def stop(self) -> None:
        with self._lock:
            self._state = "stopped"

    def status(self) -> dict:
        with self._lock:
            state = self._state
        workspace = Path(self._cfg.workspace_root)
        return {
            "state":           state,
            "workspace_root":  str(workspace.resolve()),
            "workspace_exists": workspace.exists(),
            "python_timeout":  self._cfg.python_timeout_secs,
            "blocked_modules": self._cfg.python_blocked_modules,
        }

    # ── File-system sandbox ───────────────────────────────────────────────────

    def resolve_path(self, path: str) -> Path:
        """
        Resolve *path* relative to workspace_root and verify it stays inside.

        Raises ValueError for any path that escapes the sandbox (absolute paths
        containing components that resolve outside workspace_root, ``..`` tricks,
        symlink traversal, etc.).
        """
        workspace = Path(self._cfg.workspace_root).resolve()
        # Reject absolute paths that point outside; relative paths are joined.
        target = (workspace / path).resolve()
        if not str(target).startswith(str(workspace)):
            raise ValueError(
                f"路径越界：{path!r} 解析到 {target}，不在沙箱根目录 {workspace} 内"
            )
        return target

    def is_path_allowed(self, path: str) -> bool:
        workspace = Path(self._cfg.workspace_root).resolve()
        target = (workspace / path).resolve()
        return str(target).startswith(str(workspace))

    # ── Python execution sandbox ──────────────────────────────────────────────

    def exec_python(self, code: str) -> str:
        """
        Execute *code* in a restricted namespace and return captured stdout.

        Safety measures:
        - Blocked module names are rejected at static scan level.
        - A restricted builtins dict removes dangerous callables.
        - Execution is time-bounded by python_timeout_secs using a daemon thread.
        - stdout/stderr are captured; exceptions are returned as text.
        """
        self._check_blocked_modules(code)

        safe_builtins = {
            name: __builtins__[name]  # type: ignore[index]
            for name in (
                "abs", "all", "any", "bin", "bool", "bytes", "callable",
                "chr", "complex", "dict", "dir", "divmod", "enumerate",
                "filter", "float", "format", "frozenset", "getattr",
                "globals", "hasattr", "hash", "hex", "id", "input",
                "int", "isinstance", "issubclass", "iter", "len", "list",
                "locals", "map", "max", "min", "next", "object", "oct",
                "ord", "pow", "print", "property", "range", "repr",
                "reversed", "round", "set", "setattr", "slice", "sorted",
                "str", "sum", "super", "tuple", "type", "vars", "zip",
            )
            if isinstance(__builtins__, dict) and name in __builtins__  # type: ignore[operator]
            or not isinstance(__builtins__, dict) and hasattr(__builtins__, name)
        }
        # If __builtins__ is a module, extract attributes directly
        if not isinstance(__builtins__, dict):
            safe_builtins = {
                name: getattr(__builtins__, name)
                for name in safe_builtins
                if hasattr(__builtins__, name)
            }

        namespace: dict = {"__builtins__": safe_builtins}
        stdout_capture = io.StringIO()
        result: list[str] = []
        exc_info: list[str] = []

        def _run() -> None:
            try:  # noqa: SIM105 — sandbox requires explicit capture
                with contextlib.redirect_stdout(stdout_capture):
                    exec(compile(code, "<sandbox>", "exec"), namespace)  # noqa: S102
            except Exception as exc:  # noqa: BLE001
                exc_info.append(f"{type(exc).__name__}: {exc}")

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=self._cfg.python_timeout_secs)

        if thread.is_alive():
            return f"[超时] Python 代码执行超过 {self._cfg.python_timeout_secs} 秒，已中止。"

        output = stdout_capture.getvalue()
        if exc_info:
            result.append(f"[执行错误] {exc_info[0]}")
        if output:
            result.append(output)

        combined = "\n".join(result).strip()
        if len(combined) > self._cfg.python_max_output_chars:
            combined = combined[:self._cfg.python_max_output_chars] + "\n[输出已截断]"
        return combined or "(无输出)"

    def _check_blocked_modules(self, code: str) -> None:
        """Raise ValueError if code references any blocked module name."""
        for module in self._cfg.python_blocked_modules:
            # Match 'import os', 'import os.path', 'from os import ...', '__import__("os")'
            patterns = [
                f"import {module}",
                f"from {module}",
                f'__import__("{module}")',
                f"__import__('{module}')",
            ]
            for pat in patterns:
                if pat in code:
                    raise ValueError(
                        f"Python 沙箱拒绝：检测到受限模块 {module!r}（匹配：{pat!r}）"
                    )

    # ── HTTP domain policy ────────────────────────────────────────────────────

    def check_url(self, url: str) -> bool:
        """
        Return True if *url* is allowed by the current domain policy.

        Blocked when:
        - The hostname matches any entry in http_blocked_domains (prefix match
          covers subnet ranges like "192.168." as well as exact hosts).
        - http_allowed_domains is non-empty and the hostname is NOT in it.
        """
        parsed = urlparse(url)
        host = parsed.hostname or ""
        host_lower = host.lower()

        for blocked in self._cfg.http_blocked_domains:
            if host_lower == blocked.lower() or host_lower.startswith(blocked.lower()):
                return False

        if self._cfg.http_allowed_domains:
            for allowed in self._cfg.http_allowed_domains:
                if host_lower == allowed.lower() or host_lower.endswith("." + allowed.lower()):
                    return True
            return False

        return True

    def assert_url_allowed(self, url: str) -> None:
        if not self.check_url(url):
            parsed = urlparse(url)
            raise ValueError(
                f"HTTP 沙箱拒绝：域名 {parsed.hostname!r} 不在允许范围内（SSRF 防护）"
            )
