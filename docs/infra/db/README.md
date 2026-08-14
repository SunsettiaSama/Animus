# infra/db

`src/infra/db/` 提供 Redis 与 MySQL 的薄客户端；存储后端选择由 `src/config/infra/db_config.py` 的 `DBConfig` 管理。

## 客户端

- `redis.py`：`RedisClient` 使用 `redis.from_url()` 懒创建并复用客户端，入口为 `.r`，健康检查为 `ping()`。
- `mysql.py`：`MySQLClient` 直接使用 `pymysql`，不是 SQLAlchemy engine。`conn()` 每次按需连接，正常退出时 commit，异常时 rollback，最后关闭连接。

配置对象通过 `RedisConfig.build_client()` 与 `MySQLConfig.build_client()` 创建客户端。MySQL URL 支持当前解析器接受的 `mysql+pymysql://user:password@host:port/database` 或 `mysql://...` 形式。

## DBConfig

默认配置路径是 `config/infra/db.yaml`：

```yaml
redis:
  url: redis://localhost:6379/0
  decode_responses: true
  enabled: true

mysql:
  url: mysql+pymysql://root:password@127.0.0.1:3306/knowledge
  enabled: true

storage:
  backend: auto
  json_root: .react/soul_db
  mysql_probe_timeout_sec: 1.0
```

加载入口：

- `DBConfig.load_default()`
- `DBConfig.from_yaml(path)`
- `DBConfig.from_dict(data)`

配置文件不存在时 `from_yaml()` 返回默认配置。

## `auto` / `mysql` / `json`

`DBConfig.resolved_storage_backend()` 的规则是：

- `storage.backend: mysql`：固定返回 `mysql`；调用方负责检查 `mysql.enabled` 并创建 `MySQLClient`。
- `storage.backend: json`：固定返回 `json`，使用 `JsonStorageService(storage.json_root)`。
- `storage.backend: auto`：若 `mysql.enabled` 为 false，选择 `json`；否则以 TCP 方式探测 MySQL URL 中的 host/port，可达选 `mysql`，不可达选 `json`。

探测只检查端口连通性，不验证账号、数据库或 schema。超时由 `mysql_probe_timeout_sec` 控制。

JSON 后端实现位于 `src/infra/storage/json_store.py`。collection `memory/nodes` 会写为 `.react/soul_db/memory/nodes.json`；每次写入先生成 `.tmp`，再用 `os.replace()` 替换目标文件。

Redis 的 `enabled` 独立于上述持久化后端选择，供需要短期缓存的组件自行决定是否初始化。

## 相关文档

- [config/README.md](../../config/README.md)
- [agent/soul/memory/README.md](../../agent/soul/memory/README.md)
- [storage/README.md](../../storage/README.md)
