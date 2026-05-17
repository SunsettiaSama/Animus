from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

import pymysql
import pymysql.cursors


def _parse_url(url: str) -> dict:
    """解析 mysql+pymysql://user:password@host:port/db 格式的连接 URL。"""
    url = url.replace("mysql+pymysql://", "").replace("mysql://", "")
    user_pass, rest = url.split("@", 1)
    user, password = user_pass.split(":", 1)
    host_port, db = rest.split("/", 1)
    host, port = (host_port.rsplit(":", 1) if ":" in host_port else (host_port, "3306"))
    return {
        "host": host,
        "port": int(port),
        "user": user,
        "password": password,
        "database": db,
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
    }


class MySQLClient:
    """通用 MySQL 连接管理器，每次操作按需建连、用后关闭。

    使用
    ----
        client = MySQLClient("mysql+pymysql://user:pass@host:3306/db")
        with client.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    """

    def __init__(self, url: str) -> None:
        self._kwargs = _parse_url(url)

    @contextmanager
    def conn(self) -> Generator[pymysql.connections.Connection, None, None]:
        """获取连接，成功则自动 commit，异常则 rollback，最终关闭。"""
        connection = pymysql.connect(**self._kwargs)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def ping(self) -> bool:
        """检查连接是否可用。"""
        with self.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True
