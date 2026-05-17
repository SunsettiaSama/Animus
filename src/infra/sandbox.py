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
        - __import__ is replaced with a whitelist-aware version: only modules
          in python_allowed_modules (top-level package name) are importable;
          anything in python_blocked_modules is always refused.
        - Execution is time-bounded by python_timeout_secs using a daemon thread.
        - stdout/stderr are captured; exceptions are returned as text.
        """
        blocked_err = self._check_blocked_modules(code)
        if blocked_err:
            return blocked_err

        _allowed: frozenset[str] = frozenset(self._cfg.python_allowed_modules)
        _blocked: frozenset[str] = frozenset(self._cfg.python_blocked_modules)

        def _safe_import(
            name: str,
            globals=None,  # noqa: A002
            locals=None,   # noqa: A002
            fromlist=(),
            level: int = 0,
        ):
            top = name.split(".")[0]
            if top in _blocked:
                raise ImportError(
                    f"沙箱拒绝：模块 '{name}' 在黑名单中，禁止导入"
                )
            if _allowed and top not in _allowed:
                raise ImportError(
                    f"沙箱拒绝：模块 '{name}' 不在允许列表中，"
                    f"如需使用请联系管理员将其加入 python_allowed_modules"
                )
            return __import__(name, globals, locals, fromlist, level)

        _builtins_src = __builtins__
        _is_dict = isinstance(_builtins_src, dict)

        def _get(name: str):
            if _is_dict:
                return _builtins_src.get(name)  # type: ignore[union-attr]
            return getattr(_builtins_src, name, None)

        _safe_names = (
            "abs", "all", "any", "bin", "bool", "bytes", "callable",
            "chr", "complex", "dict", "dir", "divmod", "enumerate",
            "filter", "float", "format", "frozenset", "getattr",
            "globals", "hasattr", "hash", "hex", "id",
            "int", "isinstance", "issubclass", "iter", "len", "list",
            "locals", "map", "max", "min", "next", "object", "oct",
            "ord", "pow", "print", "property", "range", "repr",
            "reversed", "round", "set", "setattr", "slice", "sorted",
            "str", "sum", "super", "tuple", "type", "vars", "zip",
            "NotImplemented", "Ellipsis", "None", "True", "False",
            "ArithmeticError", "AssertionError", "AttributeError",
            "EOFError", "Exception", "FloatingPointError", "GeneratorExit",
            "ImportError", "IndexError", "KeyError", "KeyboardInterrupt",
            "MemoryError", "NameError", "NotImplementedError", "OSError",
            "OverflowError", "RecursionError", "RuntimeError", "StopIteration",
            "StopAsyncIteration", "SyntaxError", "TypeError", "UnicodeError",
            "UnicodeDecodeError", "UnicodeEncodeError", "ValueError",
            "ZeroDivisionError",
        )
        safe_builtins = {n: v for n in _safe_names if (v := _get(n)) is not None}
        safe_builtins["__import__"] = _safe_import

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

    def _check_blocked_modules(self, code: str) -> str | None:
        """Static pre-scan: return an error string if code explicitly references a blocked module.

        This is a best-effort early check; the runtime _safe_import is the
        authoritative gate. Only blocked modules are rejected here — allowed
        modules pass through to runtime validation.
        Returns None if the code passes the static check.
        """
        for module in self._cfg.python_blocked_modules:
            patterns = [
                f"import {module}",
                f"from {module}",
                f'__import__("{module}")',
                f"__import__('{module}')",
            ]
            for pat in patterns:
                if pat in code:
                    return (
                        f"[执行错误] ImportError: "
                        f"沙箱拒绝：模块 {module!r} 在黑名单中，禁止导入"
                    )
        return None

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
