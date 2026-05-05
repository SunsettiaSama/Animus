from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from langchain_core.tools import BaseTool
from pydantic import ConfigDict

if TYPE_CHECKING:
    from pydantic import BaseModel


class BaseAction(BaseTool):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str = ""

    # Subclasses set this to a Pydantic model describing their accepted arguments.
    # ActionExecutor uses it for Zod-style validation before calling execute().
    args_model: ClassVar[type[BaseModel] | None] = None

    def execute(self, **kwargs) -> str:
        raise NotImplementedError

    def _run(self, *args, **kwargs) -> str:
        return self.execute(**kwargs)

    async def _arun(self, *args, **kwargs) -> str:
        return self._run(*args, **kwargs)
