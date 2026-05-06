# 自定义 Transport 接入其他平台

`BotService` 只依赖 `BaseTransport` 接口，理论上任何平台都可以接入。

## BaseTransport 接口

```python
class BaseTransport(ABC):
    on_event: Callable[[dict], Awaitable[None]] | None   # 由 BotService 注入

    async def start(self) -> None: ...         # 开始连接/监听
    async def stop(self) -> None: ...          # 优雅关闭
    async def call_action(action, params, timeout) -> dict: ...  # 发送动作
    def status(self) -> dict: ...              # 返回 {"state": "running"|...}
```

`on_event` 是 BotService 注入的回调，你的 Transport 收到消息后调用即可：

```python
raw = {
    "post_type": "message",
    "message_type": "private",
    "user_id": 123456,
    "message": [{"type": "text", "data": {"text": "你好"}}],
    "raw_message": "你好",
    "time": 1700000000,
    "self_id": 999999,
    "sender": {"user_id": 123456, "nickname": "Alice"},
    ...
}
if self.on_event:
    await self.on_event(raw)
```

数据格式必须符合 OneBot 11 标准（见 <https://11.onebot.dev/>）。

## 实现步骤

### 1. 继承 BaseTransport

```python
from infra.network.bot.onebot.transport.base import BaseTransport

class MyPlatformTransport(BaseTransport):
    async def start(self): ...
    async def stop(self): ...
    async def call_action(self, action, params, timeout=10.0) -> dict: ...
    def status(self) -> dict: ...
```

### 2. 在 start() 里订阅平台消息，转换为 OneBot 11 格式，调用 on_event

```python
async def start(self):
    self._task = asyncio.create_task(self._listen())

async def _listen(self):
    async for platform_msg in self._platform_stream():
        raw = self._to_onebot(platform_msg)   # 你自己的转换逻辑
        if self.on_event:
            await self.on_event(raw)
```

### 3. 在 call_action() 里把 OneBot 11 动作翻译回平台 API

```python
async def call_action(self, action, params, timeout=10.0) -> dict:
    if action == "send_private_msg":
        await self._platform_send(params["user_id"], params["message"])
        return {"status": "ok", "data": {"message_id": 0}}
    return {"status": "failed", "retcode": 1404}
```

### 4. 替换默认 Transport

在 `config/infra/bot_config.yaml` 无法直接指定自定义 transport，
需要在 `state.py` 的 `_init_infra()` 里替换：

```python
# state.py _init_infra() 末尾
from my_transport import MyPlatformTransport
transport = MyPlatformTransport(...)
self.bot_service = BotService(transport, self, bot_cfg)
self.service_registry.register("bot", self.bot_service)
```

## 示例文件

`my_transport.py` 实现了一个 HTTP Long-Poll 示例 Transport，展示了完整结构。
