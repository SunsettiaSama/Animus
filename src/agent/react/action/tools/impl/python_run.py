from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from ....action.base import BaseAction


class PythonRunArgs(BaseModel):
    code: str = Field(..., min_length=1, description="要执行的 Python 代码片段")


class PythonRunAction(BaseAction):
    name: str = "python_run"
    description: str = (
        "在受限沙箱环境中执行 Python 代码片段，捕获并返回 stdout 输出。"
        "支持基础计算、数据处理、字符串操作等；禁止访问文件系统、网络、系统模块。"
        "参数：code（Python 代码字符串）"
    )
    args_model: ClassVar[type[BaseModel]] = PythonRunArgs

    sandbox: Any = None

    def execute(self, code: str, **kwargs) -> str:
        if self.sandbox is None:
            raise RuntimeError("python_run 需要 SandboxManager 注入，沙箱未初始化。")
        return self.sandbox.exec_python(code)
