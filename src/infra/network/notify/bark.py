from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config.infra.bark_config import BarkConfig

logger = logging.getLogger(__name__)


class BarkNotifier:
    """向 Bark 服务端发送推送通知。

    Bark API 文档：https://bark.day.app/#/

    发送方式：POST {server_url}/push  Body: JSON
    字段：device_key, title, body, sound, group
    """

    def __init__(self, cfg: BarkConfig) -> None:
        self._cfg = cfg

    def update(self, cfg: BarkConfig) -> None:
        self._cfg = cfg

    def send(
        self,
        title: str,
        body: str,
        device_key: str | None = None,
    ) -> None:
        cfg = self._cfg
        if not cfg.enabled:
            logger.debug("[BarkNotifier] disabled — message skipped")
            return
        key = device_key or cfg.device_key
        if not key:
            logger.warning("[BarkNotifier] device_key not set — message skipped")
            return

        server = cfg.server_url.rstrip("/")
        url = f"{server}/push"
        payload: dict = {
            "device_key": key,
            "title":      title,
            "body":       body,
        }
        if cfg.sound:
            payload["sound"] = cfg.sound
        if cfg.group:
            payload["group"] = cfg.group

        self._do_post(url, payload)

    def _do_post(self, url: str, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
                if status != 200:
                    logger.warning("[BarkNotifier] HTTP %d from %s", status, url)
                else:
                    logger.debug("[BarkNotifier] sent OK  title=%r", payload.get("title"))
        except urllib.error.URLError as exc:
            logger.error("[BarkNotifier] request failed: %s", exc)
