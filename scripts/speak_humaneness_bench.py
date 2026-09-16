#!/usr/bin/env python3
"""speak 拟人度三维评测入口（画像匹配 × 图灵盲测 × 行为统计）。

示例（cwd = 仓库根）::

    python scripts/speak_humaneness_bench.py --limit 1 --responders direct   # 单管线小样本
    python scripts/speak_humaneness_bench.py --limit 2                       # 双管线冒烟
    python scripts/speak_humaneness_bench.py                                 # 全量（50 case × 双管线）
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from evals.speak_humaneness.__main__ import main

if __name__ == "__main__":
    main()
