# infra/db

Soul 记忆与其它需要 Redis / MySQL 的组件使用的 **薄客户端封装**。

源码：`src/infra/db/`。

---

## 模块

| 文件 | 说明 |
|---|---|
| `redis.py` | `RedisClient` — 包装 `redis.Redis` |
| `mysql.py` | `MySQLClient` — SQLAlchemy 引擎封装 |

---

## 配置

连接参数由 **`config/infra/db.yaml`** + **`DBConfig`**（`src/config/infra/db_config.py`）加载；`TaoConfig.db` 可选挂载同一配置树。

构建：`RedisConfig.build_client()`、`MySQLConfig.build_client()`。

---

## 相关文档

- [config/README.md](../../config/README.md)
- [agent/soul/memory/README.md](../../agent/soul/memory/README.md)
