"""launch — 宿主编排层（启动站后端域）。

定位（见 docs/product/launch-hub-requirements.md §3）：
- 与 agent/infra/webui 平级的顶层包，承载"启动站"的全部后端逻辑；
- 依赖方向：``run.py → launch → {config, infra, agent}``，webui 经 routers
  薄适配调用本包；**本包不得 import webui**——形态 B（服务端部署）的无头
  宿主将来复用同一套编排，其中没有 webui；
- ``launch.demos`` 子包为产品形态 A（本地部署）专属，无头宿主不得引用。

对外状态入口只有 :func:`launch.status.snapshot`——``GET /api/launch/status``
与 ``python src/run.py --check`` 的共同正本。
"""
from __future__ import annotations
