from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# config/react/tools/web_search.yaml 相对于本文件的路径
# src/config/react/tools/ → (上4级) → 项目根 → config/react/tools/web_search.yaml
_DEFAULT_YAML: Path = (
    Path(__file__).resolve().parents[4]
    / "config" / "react" / "tools" / "web_search.yaml"
)


@dataclass
class TLSConfig:
    verify: bool = True
    ca_bundle: str = ""          # 非空时用作自定义 CA 包路径


@dataclass
class RequestConfig:
    timeout: float = 10.0
    max_retries: int = 2
    headers: dict[str, str] = field(
        default_factory=lambda: {"User-Agent": "ReAct-Agent/1.0"}
    )


@dataclass
class SearchDefaults:
    safe_search: int = 1         # 0=关闭  1=中等  2=严格
    default_language: str = "auto"
    default_categories: str = "general"
    max_results_limit: int = 8   # Agent 可请求的结果数上限


@dataclass
class WebSearchConfig:
    url: str = "http://127.0.0.1:8888"
    tls: TLSConfig = field(default_factory=TLSConfig)
    request: RequestConfig = field(default_factory=RequestConfig)
    search: SearchDefaults = field(default_factory=SearchDefaults)

    # ── 工厂方法 ──────────────────────────────────────────────────────────────

    @classmethod
    def from_yaml(cls, path: str | Path) -> "WebSearchConfig":
        import yaml

        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}

        tls_d    = data.get("tls", {})
        req_d    = data.get("request", {})
        search_d = data.get("search", {})

        tls = TLSConfig(
            verify=bool(tls_d.get("verify", True)),
            ca_bundle=str(tls_d.get("ca_bundle", "") or ""),
        )
        request = RequestConfig(
            timeout=float(req_d.get("timeout", 10.0)),
            max_retries=int(req_d.get("max_retries", 2)),
            headers=dict(
                req_d.get("headers", {"User-Agent": "ReAct-Agent/1.0"})
            ),
        )
        search = SearchDefaults(
            safe_search=int(search_d.get("safe_search", 1)),
            default_language=str(search_d.get("default_language", "auto")),
            default_categories=str(search_d.get("default_categories", "general")),
            max_results_limit=int(search_d.get("max_results_limit", 8)),
        )

        return cls(
            url=str(data.get("url", "http://127.0.0.1:8888")),
            tls=tls,
            request=request,
            search=search,
        )

    @classmethod
    def load(cls) -> "WebSearchConfig":
        """从默认 YAML 路径加载；文件不存在时使用内置默认值。"""
        if _DEFAULT_YAML.exists():
            return cls.from_yaml(_DEFAULT_YAML)
        return cls()

    # ── 运行时属性 ────────────────────────────────────────────────────────────

    @property
    def effective_url(self) -> str:
        """SEARXNG_URL 环境变量优先于 yaml 中的 url。"""
        return os.environ.get("SEARXNG_URL", self.url).rstrip("/")

    @property
    def ssl_verify(self) -> bool | str:
        """返回 httpx verify 参数：bool 或自定义 CA bundle 路径。"""
        if self.tls.ca_bundle:
            return self.tls.ca_bundle
        return self.tls.verify
