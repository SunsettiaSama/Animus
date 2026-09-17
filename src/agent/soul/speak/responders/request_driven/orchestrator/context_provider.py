from __future__ import annotations

"""环境材料提供者协议（ContextProvider）。

把"给角色/导演提供环境材料"的位置从"编剧"抽象为协议：编剧是当前默认
实现（kind="screenwriter"，从剧情流/大纲读材料）；未来游戏内容、外部
世界观等可作为独立 provider 封包接入（`SpeakService.register_context_provider`），
不必改动热路径消费端。

消费端契约（`_director_dynamic_schedule` / compose）只认 provider 快照的
字段，不认具体实现：
- material_schedule：dict（inject_memory/memory_unit_ids/inject_share/
  share_indices/pass_info/material_reason）——可注入材料调度提案；
- plot_outline_text / plot_flow_text / scene_event：str——剧情/场景材料；
- source：str——来源标识（写进调度 reason，方便 trace 归因）。

注册顺序即优先级：同类 kind 后注册覆盖先注册；不同 kind 的材料调度
按注册序取第一个非空提案（"编剧提案、其它环境可接管"）。
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ContextProvider(Protocol):
    """环境材料提供者。实现方必须线程安全（可能被编排线程并发读取）。"""

    @property
    def kind(self) -> str: ...

    def snapshot(self, session_id: str) -> dict[str, Any]:
        """返回该 provider 对当前会话的材料快照（字段契约见模块 docstring）。"""
        ...


class ScreenwriterContextProvider:
    """默认 provider：从剧情流/大纲读编剧产出的材料。"""

    def __init__(self, state_store: Any) -> None:
        self._state_store = state_store

    @property
    def kind(self) -> str:
        return "screenwriter"

    def snapshot(self, session_id: str) -> dict[str, Any]:
        state = self._state_store.session(session_id.strip())
        flow = getattr(state, "plot_flow", None)
        arc = getattr(state, "plot_arc", None)
        schedule: dict[str, Any] = {}
        if flow is not None:
            schedule = {
                "inject_memory": bool(getattr(flow, "inject_memory", False)),
                "memory_unit_ids": list(getattr(flow, "memory_unit_ids", None) or []),
                "inject_share": bool(getattr(flow, "inject_share", False)),
                "share_indices": list(getattr(flow, "share_indices", None) or []),
                "pass_info": bool(getattr(flow, "pass_info", False)),
                "material_reason": str(getattr(flow, "material_reason", "") or ""),
            }
        return {
            "kind": self.kind,
            "source": "screenwriter_plot_flow",
            "material_schedule": schedule,
            "plot_outline_text": str(getattr(arc, "summary", "") or "")
            if arc is not None and getattr(arc, "ready", False)
            else "",
            "plot_flow_text": "\n".join(
                part
                for part in (
                    str(getattr(flow, "chronicle", "") or "").strip(),
                    str(getattr(flow, "focus_now", "") or "").strip(),
                )
                if part
            )
            if flow is not None and getattr(flow, "ready", False)
            else "",
            "scene_event": str(getattr(state.narrative_card, "scene_event", "") or ""),
        }


class ContextProviderRegistry:
    """有序注册表：默认装 screenwriter provider，可追加/覆盖。"""

    def __init__(self, state_store: Any | None = None) -> None:
        self._providers: list[ContextProvider] = []
        if state_store is not None:
            self._providers.append(ScreenwriterContextProvider(state_store))

    def register(self, provider: ContextProvider, *, replace: bool = True) -> None:
        if replace:
            self._providers = [p for p in self._providers if p.kind != provider.kind]
        self._providers.append(provider)

    def unregister(self, kind: str) -> None:
        self._providers = [p for p in self._providers if p.kind != kind]

    def kinds(self) -> tuple[str, ...]:
        return tuple(p.kind for p in self._providers)

    def material_schedule(self, session_id: str) -> dict[str, Any]:
        """按注册序取第一个非空材料调度提案；全空返回空 dict。"""
        for provider in self._providers:
            try:
                snap = provider.snapshot(session_id)
            except Exception:  # noqa: BLE001 - 单个 provider 故障不拖垮热路径
                continue
            schedule = snap.get("material_schedule") or {}
            if schedule.get("inject_memory") or schedule.get("inject_share"):
                return {
                    **schedule,
                    "provider_kind": str(snap.get("kind") or provider.kind),
                }
        return {}

    def plot_materials(self, session_id: str) -> dict[str, str]:
        """合并各 provider 的剧情文本（先注册者优先，同字段不覆盖）。"""
        merged: dict[str, str] = {}
        for provider in self._providers:
            try:
                snap = provider.snapshot(session_id)
            except Exception:  # noqa: BLE001
                continue
            for key in ("plot_outline_text", "plot_flow_text", "scene_event"):
                text = str(snap.get(key) or "").strip()
                if text and not merged.get(key):
                    merged[key] = text
        return merged
