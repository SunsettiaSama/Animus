"""注册目标解析：字符串包名 / soul 入口 / 可调用对象 → 可调用。

每次执行时解析（懒解析），保持注册项可序列化、模块可后加载。
"""

from __future__ import annotations

import importlib
from typing import Any, Callable


def resolve_target(target: Any, ctx: Any) -> Callable[[dict, Any], Any]:
    if callable(target):
        return target
    if isinstance(target, str):
        if target.startswith("soul:"):
            obj = ctx.soul
            for part in target[5:].split("."):
                if not part:
                    continue
                obj = getattr(obj, part)
            if callable(obj):
                return obj
            raise ValueError(f"soul target 不可调用: {target!r}")
        if ":" in target:
            module_path, attr = target.split(":", 1)
            fn = getattr(importlib.import_module(module_path), attr)
            if callable(fn):
                return fn
            raise ValueError(f"target 不可调用: {target!r}")
    raise ValueError(f"无法解析的 wake target: {target!r}（契约见 wake-registration-prd）")
