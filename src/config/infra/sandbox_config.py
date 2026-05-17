from __future__ import annotations

from dataclasses import dataclass, field

# 沙箱允许 import 的模块白名单（默认值）。
# 只有顶级包名需要列出（如 "xml" 即覆盖 xml.etree.ElementTree）。
# 留空列表（[]）表示不限制（仅黑名单生效），不建议生产使用。
_DEFAULT_ALLOWED_MODULES: list[str] = [
    # 数据 & 序列化
    "json", "csv", "base64", "struct",
    # 文本 & 正则
    "re", "string", "textwrap", "difflib", "unicodedata",
    # 数学 & 统计
    "math", "cmath", "decimal", "fractions", "random", "statistics",
    # 日期时间
    "datetime",
    # 数据结构 & 函数式
    "collections", "itertools", "functools", "heapq", "bisect",
    # 类型 & 工具
    "typing", "types", "copy", "pprint", "enum", "dataclasses", "abc",
    # 字节 & 哈希（只读运算）
    "hashlib", "hmac", "binascii",
    # XML / HTML 解析
    "xml", "html",
    # IO 缓冲（内存级）
    "io",
    # URL 工具（仅解析，不发请求）
    "urllib",
]

_DEFAULT_BLOCKED_MODULES: list[str] = [
    "os", "sys", "subprocess", "socket", "shutil", "pathlib",
    "importlib", "ctypes", "multiprocessing", "threading",
    "signal", "resource", "pty", "termios", "fcntl",
    "pickle", "shelve", "marshal",
    "builtins", "gc", "inspect", "dis",
]


@dataclass
class SandboxConfig:
    workspace_root: str = ".react/workspace"
    python_timeout_secs: int = 10
    python_max_output_chars: int = 5000
    python_allowed_modules: list[str] = field(
        default_factory=lambda: list(_DEFAULT_ALLOWED_MODULES)
    )
    python_blocked_modules: list[str] = field(
        default_factory=lambda: list(_DEFAULT_BLOCKED_MODULES)
    )
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
            python_allowed_modules=data.get(
                "python_allowed_modules", list(_DEFAULT_ALLOWED_MODULES)
            ),
            python_blocked_modules=data.get(
                "python_blocked_modules", list(_DEFAULT_BLOCKED_MODULES)
            ),
            http_allowed_domains=data.get("http_allowed_domains", []),
            http_blocked_domains=data.get(
                "http_blocked_domains",
                cls.__dataclass_fields__["http_blocked_domains"].default_factory(),
            ),
            max_file_size_bytes=int(data.get("max_file_size_bytes", 10_485_760)),
        )

    def to_yaml(self, path: str) -> None:
        import yaml
        import os
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {
            "workspace_root":          self.workspace_root,
            "python_timeout_secs":     self.python_timeout_secs,
            "python_max_output_chars": self.python_max_output_chars,
            "python_allowed_modules":  self.python_allowed_modules,
            "python_blocked_modules":  self.python_blocked_modules,
            "http_allowed_domains":    self.http_allowed_domains,
            "http_blocked_domains":    self.http_blocked_domains,
            "max_file_size_bytes":     self.max_file_size_bytes,
        }
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True)
