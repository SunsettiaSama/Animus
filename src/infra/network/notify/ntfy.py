from __future__ import annotations

import base64
import logging
import urllib.request
import urllib.error
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config.infra.ntfy_config import NtfyConfig

logger = logging.getLogger(__name__)

_PRIORITY_STRINGS = {1: "min", 2: "low", 3: "default", 4: "high", 5: "urgent"}


class NtfyNotifier:
    """向 ntfy 服务端发送推送通知。

    ntfy API 文档：https://docs.ntfy.sh/publish/

    发送方式：POST {server_url}/{topic}
    Title 放在 Header X-Title，Priority 放在 Header X-Priority。
    支持 HTTP Basic Auth（username / password）。
    """

    def __init__(self, cfg: NtfyConfig) -> None:
        self._cfg = cfg

    def update(self, cfg: NtfyConfig) -> None:
        self._cfg = cfg

    def send(
        self,
        title: str,
        body: str,
        topic: str | None = None,
    ) -> None:
        cfg = self._cfg
        if not cfg.enabled:
            logger.debug("[NtfyNotifier] disabled — message skipped")
            return
        t = topic or cfg.topic
        if not t:
            logger.warning("[NtfyNotifier] topic not set — message skipped")
            return

        server = cfg.server_url.rstrip("/")
        url = f"{server}/{t}"

        headers: dict[str, str] = {
            "Content-Type": "text/plain; charset=utf-8",
            "X-Title":      title,
            "X-Priority":   _PRIORITY_STRINGS.get(cfg.priority, "default"),
        }
        if cfg.username and cfg.password:
            creds = base64.b64encode(
                f"{cfg.username}:{cfg.password}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {creds}"

        self._do_post(url, body, headers)

    def _do_post(self, url: str, body: str, headers: dict) -> None:
        data = body.encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
                if status not in (200, 201):
                    logger.warning("[NtfyNotifier] HTTP %d from %s", status, url)
                else:
                    logger.debug("[NtfyNotifier] sent OK  title=%r", headers.get("X-Title"))
        except urllib.error.URLError as exc:
            logger.error("[NtfyNotifier] request failed: %s", exc)
