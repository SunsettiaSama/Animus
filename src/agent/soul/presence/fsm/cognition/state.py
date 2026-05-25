from __future__ import annotations

from dataclasses import dataclass

from ..narrative import compose_narrative, normalize_narrative


@dataclass
class CognitionState:
    """认知：工作记忆与思维两段自叙。"""

    working_memory: str = ""
    thinking: str = ""

    def render(self) -> str:
        return compose_narrative(
            f"工作记忆：{self.working_memory}" if normalize_narrative(self.working_memory) else "",
            f"思维：{self.thinking}" if normalize_narrative(self.thinking) else "",
        )

    def is_empty(self) -> bool:
        return not normalize_narrative(self.working_memory) and not normalize_narrative(self.thinking)

    def copy(self) -> CognitionState:
        return CognitionState(
            working_memory=self.working_memory,
            thinking=self.thinking,
        )

    def to_dict(self) -> dict:
        return {
            "working_memory": self.working_memory,
            "thinking": self.thinking,
        }

    @classmethod
    def from_dict(cls, d: dict) -> CognitionState:
        if isinstance(d.get("working_memory"), str) and isinstance(d.get("thinking"), str):
            if "working_memory" in d or "thinking" in d:
                return cls(
                    working_memory=str(d.get("working_memory", "")),
                    thinking=str(d.get("thinking", "")),
                )
        wm_raw = d.get("working_memory")
        th_raw = d.get("thinking")
        if isinstance(wm_raw, dict):
            wm = normalize_narrative(str(wm_raw.get("focus", "")))
            slots = [
                normalize_narrative(str(item))
                for item in wm_raw.get("slots", [])
                if normalize_narrative(str(item))
            ]
            if slots:
                wm = compose_narrative(wm, "、".join(slots))
        else:
            wm = normalize_narrative(str(d.get("focus", "")))
        if isinstance(th_raw, dict):
            th = normalize_narrative(str(th_raw.get("thread", "")))
        else:
            th = normalize_narrative(str(d.get("thread", "")))
        return cls(working_memory=wm, thinking=th)
