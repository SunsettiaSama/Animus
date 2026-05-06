from __future__ import annotations

import json

from agent.react.action.executor import ActionExecutor


class ScriptActionExecutor(ActionExecutor):
    """
    A scripted ActionExecutor for benchmark and integration tests.

    Tool responses are pre-defined in *tool_script*:
      {"web_search": ["result 1", "result 2"], "calculator": ["42"]}

    Each call to run() for a given tool advances its internal cursor.
    When the cursor reaches the end of the script list the last entry is
    repeated, matching the same semantics as MockLLM.

    Unknown tools return a '[mock] unknown tool' error string rather than
    raising, so the TaoLoop can observe the error and attempt recovery.
    """

    def __init__(self, tool_script: dict[str, list[str]]) -> None:
        super().__init__()
        self._script: dict[str, list[str]] = {
            k: list(v) for k, v in tool_script.items()
        }
        self._idx: dict[str, int] = {}

    # ── Overrides ──────────────────────────────────────────────────────────────

    @property
    def available_actions(self) -> list[str]:
        return sorted(set(self._script) | set(self._instances))

    def run(self, json_input: str) -> str:
        payload: dict = json.loads(json_input)
        name: str = payload.get("action", "")

        # Registered instances (e.g. skills like delegate_task) take precedence.
        if name in self._instances:
            return super().run(json_input)

        if name not in self._script:
            return f"[mock] unknown tool: {name!r}. Available: {self.available_actions}"

        script = self._script[name]
        idx = self._idx.get(name, 0)
        output = script[min(idx, len(script) - 1)]
        self._idx[name] = idx + 1
        return output

    def reset(self) -> None:
        """Reset all script cursors (useful between test cases)."""
        self._idx.clear()
