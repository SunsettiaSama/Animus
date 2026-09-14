"""guide — 失败项 → 人话原因 + 修复指引（R1.3）。

check id 与 probes 输出一一对应；文案面向"双击 start.bat 进来的用户"，
指引只指向可视化入口（/console 设置页），不要求用户改 yaml/代码。
"""
from __future__ import annotations

# id → (标签, 修复指引)
HINTS: dict[str, tuple[str, str]] = {
    "llm": ("LLM 未加载", "进入控制室 → 设置 → Core，配置后点 Save & Apply"),
    "llm_degraded": ("LLM 降级运行", "检查模型服务是否在线，或在控制室 → 设置 → Core 重新应用"),
    "config": ("配置装载失败", "检查 config/agent/run.yaml 与 config/llm_core/ 是否完整"),
    "storage": ("存储后端不可用", "config/infra/db.yaml 设为 json，或启动 MySQL（Docker）"),
    "persona_enabled": ("人格演化未启用", "进入控制室 → 设置 → 人格演化 → 启用（Soul 启动前置条件）"),
    "profile": ("人格画像缺失", "进入控制室 → 设置 → 人格演化，填写并保存画像"),
    "soul": ("Soul 未运行", "等待启动完成；若持续失败，查看下方错误信息"),
    "speak": ("Speak 未就绪", "Soul 运行中但对话管线未初始化，稍候；持续异常请重启服务"),
    "embedding_warm": ("Embedding 未预热", "首次检索时会自动加载；也可在控制室手动预热"),
}


def hint(check_id: str) -> tuple[str, str]:
    return HINTS.get(check_id, (check_id, ""))
