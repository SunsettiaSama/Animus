# 兼容层：ToolRegistry 和 ToolMeta 已迁移至 react.action.tool.registry
# 此文件仅做转发，不再包含实体定义
from react.action.tool.registry import ToolMeta, ToolRegistry

__all__ = ["ToolMeta", "ToolRegistry"]
