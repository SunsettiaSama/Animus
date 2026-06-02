from __future__ import annotations

__all__ = ["MySQLClient", "RedisClient"]


def __getattr__(name: str):
    if name == "MySQLClient":
        from .mysql import MySQLClient

        return MySQLClient
    if name == "RedisClient":
        from .redis import RedisClient

        return RedisClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
