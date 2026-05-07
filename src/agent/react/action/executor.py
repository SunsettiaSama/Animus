from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain_core.tools import BaseTool
from pydantic import ValidationError

from .base import BaseAction


def _validate_args(action_cls: type[BaseAction], args: dict) -> dict:
    """
    Validate and coerce *args* through the action's args_model (Pydantic schema).

    Returns the validated, coerced dict.  Raises ValueError with a human-readable
    message when validation fails, so the LLM can self-correct.
    """
    schema = getattr(action_cls, "args_model", None)
    if schema is None:
        return args
    validated = schema.model_validate(args)
    return validated.model_dump()


def _validate_args_instance(action: BaseAction, args: dict) -> dict:
    schema = getattr(type(action), "args_model", None)
    if schema is None:
        return args
    validated = schema.model_validate(args)
    return validated.model_dump()


class ActionExecutor:
    """
    工具执行器。

    支持三种注册方式：
    - register(cls)               → 类注册（BaseAction 子类），每次调用时实例化
    - register_instance(action)   → 实例注册（BaseAction 实例，持有外部依赖）
    - register_lc_tool(tool)      → LangChain BaseTool 实例注册（MCP 工具等）

    run() 调用优先级：
      instances > lc_tools > registry

    参数校验（Zod 风格）：
      若工具类定义了 args_model（Pydantic BaseModel 子类），run() 会在执行前
      使用该模型对输入参数进行验证和类型强制转换，并在校验失败时抛出
      带有清晰描述的 ValueError。
    """

    def __init__(self, event_sink=None) -> None:
        self._registry: dict[str, type[BaseAction]] = {}
        self._instances: dict[str, BaseAction] = {}
        self._lc_tools: dict[str, BaseTool] = {}
        self._event_sink = event_sink  # Callable[[str, dict, str], None] | None

    def set_event_sink(self, sink) -> None:
        self._event_sink = sink

    # ── 注册 ──────────────────────────────────────────────────────────────────

    def register(self, action_cls: type[BaseAction]) -> type[BaseAction]:
        name = action_cls.model_fields["name"].default
        self._registry[name] = action_cls
        return action_cls

    def register_instance(self, action: BaseAction) -> BaseAction:
        self._instances[action.name] = action
        return action

    def register_lc_tool(self, tool: BaseTool) -> BaseTool:
        self._lc_tools[tool.name] = tool
        return tool

    # ── 执行 ──────────────────────────────────────────────────────────────────

    def run_many(self, calls: list[dict]) -> list[str]:
        """Execute multiple action calls in parallel using ThreadPoolExecutor.

        Each entry in *calls* must be ``{"action": str, "args": dict}``.
        Results are returned in the same order as *calls* regardless of
        completion order.  Exceptions inside individual calls are caught and
        returned as error strings so that one failure does not abort the batch.
        """
        if not calls:
            return []
        if len(calls) == 1:
            return [self.run(json.dumps({"action": calls[0]["action"], "args": calls[0].get("args", {})}))]

        results: list[str] = [""] * len(calls)
        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            futures = {
                pool.submit(
                    self.run,
                    json.dumps({"action": c["action"], "args": c.get("args", {})}, ensure_ascii=False),
                ): idx
                for idx, c in enumerate(calls)
            }
            for future in as_completed(futures):
                idx = futures[future]
                results[idx] = future.result()
        return results

    def run(self, json_input: str) -> str:
        payload: dict = json.loads(json_input)
        action_name: str = payload["action"]
        raw_args: dict = payload.get("args", {})

        # ── Name resolution (fuzzy fallback for typos) ────────────────────────
        # Only attempt fuzzy matching when the exact name is unknown across all
        # three lookup tables, to avoid silent misrouting of valid names.
        if (
            action_name not in self._instances
            and action_name not in self._lc_tools
            and action_name not in self._registry
        ):
            import difflib
            candidates = difflib.get_close_matches(
                action_name, self.available_actions, n=1, cutoff=0.75
            )
            if candidates:
                action_name = candidates[0]
            else:
                return (
                    f"[工具执行错误] 未知工具: {action_name!r}。"
                    f"可用工具: {self.available_actions}"
                )

        if action_name in self._instances:
            instance = self._instances[action_name]
            args = self._coerce(instance, raw_args, source="instance")
            try:
                result = instance.execute(**args)
                if self._event_sink is not None:
                    self._event_sink(action_name, args, result)
                return result
            except Exception as exc:
                return f"[工具执行错误] {type(exc).__name__}: {exc}"

        if action_name in self._lc_tools:
            try:
                result = str(self._lc_tools[action_name].invoke(raw_args))
                if self._event_sink is not None:
                    self._event_sink(action_name, raw_args, result)
                return result
            except Exception as exc:
                return f"[工具执行错误] {type(exc).__name__}: {exc}"

        action_cls = self._registry[action_name]
        args = self._coerce(action_cls, raw_args, source="class")
        try:
            result = action_cls().execute(**args)
            if self._event_sink is not None:
                self._event_sink(action_name, args, result)
            return result
        except Exception as exc:
            return f"[工具执行错误] {type(exc).__name__}: {exc}"

    def _coerce(
        self,
        target: type[BaseAction] | BaseAction,
        raw_args: dict,
        source: str,
    ) -> dict:
        """Run Pydantic validation; convert ValidationError to a readable ValueError."""
        cls = target if isinstance(target, type) else type(target)
        schema = getattr(cls, "args_model", None)
        if schema is None:
            return raw_args
        try:
            return schema.model_validate(raw_args).model_dump()
        except ValidationError as exc:
            errors = "; ".join(
                f"{' -> '.join(str(loc) for loc in e['loc'])}: {e['msg']}"
                for e in exc.errors()
            )
            raise ValueError(
                f"工具 {cls.model_fields['name'].default!r} 参数校验失败 — {errors}"
            ) from exc

    # ── LangChain 接口 ────────────────────────────────────────────────────────

    def as_langchain_tools(self) -> list[BaseTool]:
        tools: list[BaseTool] = [cls() for cls in self._registry.values()]
        tools.extend(self._instances.values())
        tools.extend(self._lc_tools.values())
        return tools

    # ── 查询 ──────────────────────────────────────────────────────────────────

    @property
    def available_actions(self) -> list[str]:
        return sorted(set(self._registry) | set(self._instances) | set(self._lc_tools))
