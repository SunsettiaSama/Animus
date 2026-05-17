from __future__ import annotations

import redis as _redis


class RedisClient:
    """通用 Redis 客户端封装。

    懒初始化：首次访问 `.r` 属性时才真正建立连接池。

    使用
    ----
        client = RedisClient("redis://localhost:6379/0")
        client.r.set("key", "value", ex=60)
        value = client.r.get("key")
    """

    def __init__(self, url: str, decode_responses: bool = True) -> None:
        self._url = url
        self._decode_responses = decode_responses
        self._client: _redis.Redis | None = None

    @property
    def r(self) -> _redis.Redis:
        """返回 Redis 客户端实例（连接池复用）。"""
        if self._client is None:
            self._client = _redis.from_url(
                self._url,
                decode_responses=self._decode_responses,
            )
        return self._client

    def ping(self) -> bool:
        return bool(self.r.ping())
