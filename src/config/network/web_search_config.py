from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class _RequestConfig:
    timeout: int = 10
    max_retries: int = 2
    headers: dict = field(default_factory=lambda: {"User-Agent": "ReAct-Agent/1.0"})


@dataclass
class _SearchParamsConfig:
    safe_search: int = 1
    default_language: str = "auto"
    default_categories: str = "general"
    max_results_limit: int = 8


@dataclass
class _TLSConfig:
    verify: bool = True
    ca_bundle: str = ""


@dataclass
class WebSearchConfig:
    url: str = "http://127.0.0.1:8888"
    tls: _TLSConfig = field(default_factory=_TLSConfig)
    request: _RequestConfig = field(default_factory=_RequestConfig)
    search: _SearchParamsConfig = field(default_factory=_SearchParamsConfig)

    @property
    def effective_url(self) -> str:
        return os.environ.get("SEARXNG_URL", self.url).rstrip("/")

    @property
    def ssl_verify(self):
        if self.tls.ca_bundle:
            return self.tls.ca_bundle
        return self.tls.verify

    @classmethod
    def load(cls, path: str | None = None) -> WebSearchConfig:
        if path is None:
            from config import paths
            path = str(paths.web_search_config_yaml)

        if not os.path.exists(path):
            return cls()

        import yaml

        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}

        tls_d = data.get("tls", {}) or {}
        req_d = data.get("request", {}) or {}
        search_d = data.get("search", {}) or {}
        headers_d = req_d.get("headers", {}) or {"User-Agent": "ReAct-Agent/1.0"}

        return cls(
            url=data.get("url", "http://127.0.0.1:8888"),
            tls=_TLSConfig(
                verify=bool(tls_d.get("verify", True)),
                ca_bundle=tls_d.get("ca_bundle", ""),
            ),
            request=_RequestConfig(
                timeout=int(req_d.get("timeout", 10)),
                max_retries=int(req_d.get("max_retries", 2)),
                headers=headers_d,
            ),
            search=_SearchParamsConfig(
                safe_search=int(search_d.get("safe_search", 1)),
                default_language=search_d.get("default_language", "auto"),
                default_categories=search_d.get("default_categories", "general"),
                max_results_limit=int(search_d.get("max_results_limit", 8)),
            ),
        )
