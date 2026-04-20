from __future__ import annotations

from langchain_core.tools import BaseTool


class BaseAction(BaseTool):
    name: str
    description: str = ""

    def execute(self, **kwargs) -> str:
        raise NotImplementedError

    def _run(self, *args, **kwargs) -> str:
        return self.execute(**kwargs)

    async def _arun(self, *args, **kwargs) -> str:
        return self._run(*args, **kwargs)
