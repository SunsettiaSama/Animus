# desktop_pet — 接入 Soul 的桌宠互动 demo

把 speak 角色放生到桌面上：无边框置顶透明窗口，角色自己闲逛、可拖拽抛掷，
头顶气泡流式显示 Soul 的回复；沉默/等待/主动开场等主体性行为全部可视。

## 运行（先启动 Soul：`python src/run.py`）

```bash
set PYTHONPATH=src
python demos/desktop_pet/main.py
python demos/desktop_pet/main.py --char he --scale 4     # 换角色/放大
python demos/desktop_pet/main.py --smoke                 # 无头自检（不连 soul）
```

## 交互

| 操作 | 行为 |
|---|---|
| Enter | 打开输入条；再按 Enter 发送（打字期间每 0.5s 上报 `typing_pulse` 草稿，soul 能感知"对方正在打字"） |
| 鼠标拖拽角色 | 抓起；快速甩动松手 = 抛掷（带物理） |
| 短按角色 | 小反应（挤压 + 表情） |
| Esc | 关闭 |

## Soul 接线（soul_link.py）

- 复用 `src/client/speak_ws.py`，连 `/ws/speak/run`（纯 speak 生命线，与 WebUI 同协议）
- `session_id=live:desktop-pet`、`channel_id=desktop-pet` —— 与 WebUI 的 `live:<channelId>` 约定一致，
  enter greeting / poll 阶梯 / 议程到点等主动链路照常工作
- `delivery_mode=simulated`：soul 侧输出整块 speak + `agent_typing` 节奏，气泡观感自然
- 主动性可视：server_initiated turn → 头顶「💬（主动找你）」+ 气泡；`silence`/`wait` 字段 →
  角色眯眼 `z z` 姿态；模型行使沉默权（空 answer）→ 头顶轻「…」，不出泡

## 字段消费契约（与 WebUI protocol/speak_fields.js 对齐）

speak → 主气泡；observe/outline → 次级灰泡；agent_typing → 打字指示；
silence/wait → 姿态；thought/tag/chunk/state/finish → 忽略。
