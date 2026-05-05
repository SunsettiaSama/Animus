from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SandboxConfig:
    workspace_root: str = ".react/workspace"
    python_timeout_secs: int = 10
    python_max_output_chars: int = 5000
    python_blocked_modules: list[str] = field(default_factory=lambda: [
        "os", "sys", "subprocess", "socket", "shutil", "pathlib",
        "importlib", "ctypes", "multiprocessing", "threading",
        "signal", "resource", "pty", "termios", "fcntl",
    ])
    http_allowed_domains: list[str] = field(default_factory=list)
    http_blocked_domains: list[str] = field(default_factory=lambda: [
        "localhost", "127.0.0.1", "0.0.0.0", "::1",
        "169.254.169.254",
        "10.", "172.16.", "172.17.", "172.18.", "172.19.",
        "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
        "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
        "172.30.", "172.31.", "192.168.",
    ])
    max_file_size_bytes: int = 10_485_760

    @classmethod
    def from_yaml(cls, path: str) -> SandboxConfig:
        import yaml
        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls(
            workspace_root=data.get("workspace_root", ".react/workspace"),
            python_timeout_secs=int(data.get("python_timeout_secs", 10)),
            python_max_output_chars=int(data.get("python_max_output_chars", 5000)),
            python_blocked_modules=data.get("python_blocked_modules", cls.__dataclass_fields__["python_blocked_modules"].default_factory()),
            http_allowed_domains=data.get("http_allowed_domains", []),
            http_blocked_domains=data.get("http_blocked_domains", cls.__dataclass_fields__["http_blocked_domains"].default_factory()),
            max_file_size_bytes=int(data.get("max_file_size_bytes", 10_485_760)),
        )

    def to_yaml(self, path: str) -> None:
        import yaml
        import os
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {
            "workspace_root":         self.workspace_root,
            "python_timeout_secs":    self.python_timeout_secs,
            "python_max_output_chars": self.python_max_output_chars,
            "python_blocked_modules": self.python_blocked_modules,
            "http_allowed_domains":   self.http_allowed_domains,
            "http_blocked_domains":   self.http_blocked_domains,
            "max_file_size_bytes":    self.max_file_size_bytes,
        }
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True)
