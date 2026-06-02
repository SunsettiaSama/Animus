#!/usr/bin/env python3
"""Persona 真实 LLM 冒烟：general 切片 + 自叙合成 + compose（≤100 字提交 orchestrator）。"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_LLM_CANDIDATES = [
    ROOT / "config" / "llm_core" / "config.yaml",
    ROOT / "config" / "llm.yaml",
]
IDENTITY_PROMPT_TARGET = 150
IDENTITY_HARD_MAX = 200


def _sep(title: str) -> None:
    print(f"\n{'=' * 72}\n  {title}\n{'=' * 72}", flush=True)


def _ensure_pkg(name: str, path: Path | None = None) -> None:
    if name in sys.modules:
        return
    mod = types.ModuleType(name)
    if path is not None:
        mod.__path__ = [str(path)]
    sys.modules[name] = mod


def _load_module(relpath: str, fullname: str) -> object:
    path = SRC / relpath
    spec = importlib.util.spec_from_file_location(fullname, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    mod = importlib.util.module_from_spec(spec)
    parent = fullname.rsplit(".", 1)[0] if "." in fullname else ""
    mod.__package__ = parent
    sys.modules[fullname] = mod
    spec.loader.exec_module(mod)
    return mod


def _bootstrap() -> None:
    for name, rel in (
        ("agent", SRC / "agent"),
        ("agent.soul", SRC / "agent" / "soul"),
        ("agent.soul.persona", SRC / "agent" / "soul" / "persona"),
        ("agent.soul.persona.distill", SRC / "agent" / "soul" / "persona" / "distill"),
        ("agent.soul.speak", SRC / "agent" / "soul" / "speak"),
        ("agent.soul.speak.llm", SRC / "agent" / "soul" / "speak" / "llm"),
        ("agent.soul.speak.orchestrator", SRC / "agent" / "soul" / "speak" / "orchestrator"),
        (
            "agent.soul.speak.orchestrator.persona",
            SRC / "agent" / "soul" / "speak" / "orchestrator" / "persona",
        ),
        (
            "agent.soul.speak.orchestrator.persona.compose",
            SRC / "agent" / "soul" / "speak" / "orchestrator" / "persona" / "compose",
        ),
        (
            "agent.soul.speak.orchestrator.persona.identity",
            SRC / "agent" / "soul" / "speak" / "orchestrator" / "persona" / "identity",
        ),
        (
            "agent.soul.speak.orchestrator.persona.narrative",
            SRC / "agent" / "soul" / "speak" / "orchestrator" / "persona" / "narrative",
        ),
        (
            "agent.soul.speak.orchestrator.persona.presence",
            SRC / "agent" / "soul" / "speak" / "orchestrator" / "persona" / "presence",
        ),
        (
            "agent.soul.speak.io.inbound.compose",
            SRC / "agent" / "soul" / "speak" / "io" / "inbound" / "compose",
        ),
    ):
        _ensure_pkg(name, rel)

    _load_module("agent/soul/persona/distill/schema.py", "agent.soul.persona.distill.schema")
    _load_module(
        "agent/soul/speak/io/inbound/compose/render.py",
        "agent.soul.speak.io.inbound.compose.render",
    )
    _load_module("agent/soul/speak/llm/engine.py", "agent.soul.speak.llm.engine")
    _load_module("agent/soul/voice_rules.py", "agent.soul.voice_rules")
    _load_module(
        "agent/soul/speak/orchestrator/persona/limits.py",
        "agent.soul.speak.orchestrator.persona.limits",
    )
    _load_module(
        "agent/soul/speak/orchestrator/persona/prompt_rules.py",
        "agent.soul.speak.orchestrator.persona.prompt_rules",
    )
    _load_module(
        "agent/soul/speak/orchestrator/persona/compose/state.py",
        "agent.soul.speak.orchestrator.persona.compose.state",
    )
    _load_module(
        "agent/soul/speak/orchestrator/persona/compose/records.py",
        "agent.soul.speak.orchestrator.persona.compose.records",
    )
    _load_module(
        "agent/soul/speak/orchestrator/persona/compose/input.py",
        "agent.soul.speak.orchestrator.persona.compose.input",
    )
    _load_module(
        "agent/soul/speak/orchestrator/persona/compose/refine.py",
        "agent.soul.speak.orchestrator.persona.compose.refine",
    )
    _load_module(
        "agent/soul/speak/orchestrator/persona/compose/store.py",
        "agent.soul.speak.orchestrator.persona.compose.store",
    )
    _load_module(
        "agent/soul/speak/orchestrator/persona/identity/collect.py",
        "agent.soul.speak.orchestrator.persona.identity.collect",
    )
    _load_module(
        "agent/soul/speak/orchestrator/persona/presence/collect.py",
        "agent.soul.speak.orchestrator.persona.presence.collect",
    )
    _load_module(
        "agent/soul/speak/orchestrator/persona/narrative/distill.py",
        "agent.soul.speak.orchestrator.persona.narrative.distill",
    )
    _load_module(
        "agent/soul/speak/orchestrator/persona/compose/service.py",
        "agent.soul.speak.orchestrator.persona.compose.service",
    )


def _load_llm_config():
    from config.llm_core.config import LLMConfig

    api_key = os.environ.get("REACT_TEST_LLM_API_KEY", "").strip()
    model = os.environ.get("REACT_TEST_LLM_MODEL", "").strip()
    base_url = os.environ.get("REACT_TEST_LLM_BASE_URL", "").strip() or None
    if api_key and model:
        return LLMConfig(
            backend="openai",
            api_key=api_key,
            model=model,
            base_url=base_url,
            max_tokens=int(os.environ.get("REACT_TEST_LLM_MAX_TOKENS", "512")),
            temperature=float(os.environ.get("REACT_TEST_LLM_TEMPERATURE", "0.3")),
        )
    for path in _LLM_CANDIDATES:
        if path.is_file():
            cfg = LLMConfig.from_yaml(str(path))
            if cfg.api_key.strip() and cfg.model.strip():
                if cfg.backend not in ("openai", "vllm", "vllm-clone"):
                    cfg.backend = "openai"
                return cfg
    return None


def main() -> None:
    _bootstrap()
    distill_mod = _load_module(
        "agent/soul/persona/distill/writer.py",
        "agent.soul.persona.distill.writer",
    )
    from agent.soul.persona.profile.profile import PersonaProfile
    from agent.soul.persona.self_concept.concept import SelfConcept
    from agent.soul.speak.llm.engine import SpeakLLMEngine
    from agent.soul.speak.orchestrator.persona.compose.service import PersonaComposeService
    from agent.soul.speak.orchestrator.persona.narrative.distill import distill_self_narrative
    from infra.llm import LLM

    cfg = _load_llm_config()
    if cfg is None:
        print("未找到 LLM 配置，退出。", flush=True)
        raise SystemExit(1)

    print(
        f"LLM: {cfg.model}  提示目标={IDENTITY_PROMPT_TARGET} 字  硬截断={IDENTITY_HARD_MAX} 字",
        flush=True,
    )
    engine = SpeakLLMEngine(LLM(cfg))

    _sep("1) PersonaDistillWriter · general（profile + self_concept → 提示150/硬截200）")
    profile = PersonaProfile(
        name="莉奈娅",
        core_traits=["好奇", "温和"],
        interpersonal_style="开朗，乐于分享观察",
        built=True,
        built_at="test",
    )
    concept = SelfConcept(narrative="我是探险队的记录者，习惯先倾听再整理线索。")
    pack = distill_mod.PersonaDistillWriter(LLM(cfg)).distill(
        profile,
        concept,
        attention_keywords=["探险"],
        source_revision="smoke|",
    )
    general = pack.slice("general")
    print(f"len={len(general)}\n{general}", flush=True)
    assert len(general) <= IDENTITY_HARD_MAX

    _sep("2) distill_self_narrative（stable + presence → 硬截200）")
    narrative = distill_self_narrative(
        engine,
        stable_portrait=general,
        state_portrait="此刻有些兴奋但克制。",
    )
    print(f"len={len(narrative)}\n{narrative}", flush=True)
    assert len(narrative) <= IDENTITY_HARD_MAX

    _sep("3) PersonaComposeService · 提交 orchestrator 的 self_narrative")
    from agent.soul.persona.distill.schema import PERSONA_DISTILL_SCHEMA_VERSION

    snap = {
        "profile": {"name": "莉奈娅", "core_traits": ["好奇"], "built": True, "built_at": "test"},
        "self_concept": {"narrative": "探险队记录者。", "beliefs": []},
        "attention_keywords": [],
        "persona_distill": {
            "schema_version": PERSONA_DISTILL_SCHEMA_VERSION,
            "source_revision": "smoke|",
            "distilled_at": "2026-01-01T00:00:00+00:00",
            "slices": {"general": general, "dialogue": "", "story": "", "reasoning": "", "memory_anchor": ""},
        },
    }

    class _Port:
        def get_persona_snapshot(self, *, session_id: str = "tao") -> dict:
            return snap

    pres = MagicMock()
    pres.session_id = "smoke"
    pres.state.affect.render.return_value = "兴奋但克制"
    pres.state.somatic.render.return_value = ""
    pres.state.cognition.thinking = ""
    pres.state.perception.render.return_value = ""

    class _Presence:
        def snapshot(self, session_id: str):
            return pres

    state = PersonaComposeService(_Port(), _Presence(), llm=engine).compose_and_set(
        session_id="smoke-compose",
        turn_index=1,
        force=True,
    )
    print(
        f"stable({len(state.stable_portrait)}) narrative({len(state.self_narrative)})\n"
        f"【自叙】{state.self_narrative}",
        flush=True,
    )
    assert len(state.self_narrative) <= IDENTITY_HARD_MAX
    _sep("完成 · 上层 guidance 使用 bundle.persona.self_narrative 作为 persona_portrait")


if __name__ == "__main__":
    main()
