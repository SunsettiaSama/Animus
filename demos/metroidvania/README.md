# 星陨之痕 · Starfall Echoes

一个类银河恶魔城（Metroidvania）双章节 Demo。纯 HTML5 Canvas + 原生 JavaScript，零依赖、零构建。

## 运行

直接双击打开 `index.html`（推荐 Chrome / Edge）。

或者起个本地服务器：

```bash
python -m http.server 8000
# 浏览器访问 http://localhost:8000
```

## 操作

| 动作 | 按键 |
|---|---|
| 移动 | ←→ / A D |
| 跳跃（可二段跳） | Z / K / 空格 |
| 挥剑（三段连击） | X / J |
| 冲刺（获得后） | C / L / Shift |
| 下劈弹跳 | 空中按住 ↓ + 攻击 |
| 蹬墙跳 | 贴墙下滑时按跳跃 |
| 暂停 | Esc / P |
| 静音 | M |

## 流程（约 10~15 分钟）

- **第一章 · 幽暗矿脉**：学习移动与战斗 → 回声竖井学会蹬墙跳 → 取得「疾行之靴」（冲刺）→ 魔像巢穴击败 **矿洞魔像**
- **第二章 · 星坠回廊**：星坠之桥取得「星羽」（二段跳）→ 摘星之塔攀爬 → 核心圣殿击败 **星核守望者** → 进入星门通关

能力解锁即探索钥匙：深沟需要冲刺、高塔需要二段跳——典型的银河城能力门设计。
灯台（检查点）会完全恢复生命。

## 结构

```
index.html      入口
style.css       画布样式
js/audio.js     WebAudio 程序化音效 + 极简 BGM
js/input.js     键盘输入
js/levels.js    6 个房间的 ASCII 地图 + 碰撞世界
js/particles.js 粒子系统
js/player.js    玩家手感（土狼时间/跳跃缓冲/蹬墙跳/冲刺/下劈）
js/enemies.js   爬行者/飞翼/炮手/弹幕/道具/灯台
js/boss.js      两个 Boss
js/game.js      状态机 + 渲染 + HUD
```

## 调参

手感相关常量在 `js/player.js` 顶部的 `PHYS`；关卡改 `js/levels.js` 里的 ASCII 地图即可（`#`砖 `=`平台 `^`刺 `k`灯台 `1-5`传送门）。
