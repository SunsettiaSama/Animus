from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_STITCH_PATH = _ROOT / "agent" / "soul" / "speak" / "orchestrator" / "prompt_stitch.py"

_spec = importlib.util.spec_from_file_location("prompt_stitch_isolated", _STITCH_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["prompt_stitch_isolated"] = _mod
assert _spec.loader is not None
_spec.loader.exec_module(_mod)

assemble_turn_system = _mod.assemble_turn_system


@dataclass
class _System:
    role: str = ""
    output_format: str = ""


@dataclass
class _Identity:
    narrative: str = ""

    def render(self) -> str:
        return self.narrative.strip()


@dataclass
class _Relational:
    interactor_portrait: str = ""

    def render(self) -> str:
        return self.interactor_portrait.strip()


@dataclass
class _Persona:
    identity: _Identity = field(default_factory=_Identity)
    relational: _Relational = field(default_factory=_Relational)

    def render_blocks(self) -> list[str]:
        block = self.identity.render()
        return [block] if block else []

    def render_interactor_block(self) -> str:
        return self.relational.render()


@dataclass
class _Scene:
    world_scene: str = ""

    def render_blocks(self) -> list[str]:
        text = self.world_scene.strip()
        return [text] if text else []


@dataclass
class _Guidance:
    control_arc: str = ""
    context_distill: str = ""
    working_memory: str = ""

    def render_orchestrator_blocks(self) -> list[str]:
        return [self.control_arc.strip()] if self.control_arc.strip() else []


@dataclass
class _Bundle:
    system: _System = field(default_factory=_System)
    persona: _Persona = field(default_factory=_Persona)
    scene: _Scene = field(default_factory=_Scene)
    guidance: _Guidance = field(default_factory=_Guidance)


def test_assemble_turn_system_order():
    bundle = _Bundle(
        system=_System(
            role="你是会话中的角色。",
            output_format="回复时请用成对标签组织输出。",
        ),
        persona=_Persona(
            identity=_Identity(narrative="你是博物学家。"),
            relational=_Relational(
                interactor_portrait="与你交谈的是访客，特质偏好奇。",
            ),
        ),
        scene=_Scene(world_scene="风起地·傍晚"),
        guidance=_Guidance(
            control_arc="用户可能在等你先开口。你状态平稳，打算短句接住对方。",
            context_distill="在此之前，你们已经谈过的脉络可概括为：\n- 你们谈到了蒙德城。",
            working_memory="尚未纳入上述摘要的最近几轮对白如下：\n用户：你好\n我：你好呀",
        ),
    )
    text = assemble_turn_system(bundle)
    assert "【编排态" not in text
    assert "【对话引导 ·" not in text
    assert "你是博物学家。" in text
    assert "在此之前，你们已经谈过的脉络" in text
    assert "尚未纳入上述摘要的最近几轮对白" in text
    assert "回复时请用成对标签" in text
    assert text.index("你是博物学家") < text.index("在此之前")
    assert text.index("在此之前") < text.index("尚未纳入")
    assert text.index("尚未纳入") < text.index("回复时请")
