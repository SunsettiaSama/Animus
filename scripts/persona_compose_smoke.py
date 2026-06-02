#!/usr/bin/env python3
"""Persona compose smoke：fallback / 真实 LLM，打印 identity+presence 出站 prompt。"""

from __future__ import annotations

import importlib.util
import json
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
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

_LLM_CANDIDATES = [
    ROOT / "config" / "llm_core" / "config.yaml",
    ROOT / "config" / "llm.yaml",
]


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


def _bootstrap_persona_modules():
    for name, rel in (
        ("agent", SRC / "agent"),
        ("agent.soul", SRC / "agent" / "soul"),
        ("agent.soul.persona", SRC / "agent" / "soul" / "persona"),
        ("agent.soul.persona.distill", SRC / "agent" / "soul" / "persona" / "distill"),
        ("agent.soul.speak", SRC / "agent" / "soul" / "speak"),
        ("agent.soul.speak.io", SRC / "agent" / "soul" / "speak" / "io"),
        ("agent.soul.speak.io.inbound", SRC / "agent" / "soul" / "speak" / "io" / "inbound"),
        (
            "agent.soul.speak.io.inbound.compose",
            SRC / "agent" / "soul" / "speak" / "io" / "inbound" / "compose",
        ),
        ("agent.soul.speak.orchestrator", SRC / "agent" / "soul" / "speak" / "orchestrator"),
        (
            "agent.soul.speak.orchestrator.persona",
            SRC / "agent" / "soul" / "speak" / "orchestrator" / "persona",
        ),
        (
            "agent.soul.speak.orchestrator.persona.blocks",
            SRC / "agent" / "soul" / "speak" / "orchestrator" / "persona" / "blocks",
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
            "agent.soul.speak.orchestrator.persona.presence",
            SRC / "agent" / "soul" / "speak" / "orchestrator" / "persona" / "presence",
        ),
        (
            "agent.soul.speak.orchestrator.persona.narrative",
            SRC / "agent" / "soul" / "speak" / "orchestrator" / "persona" / "narrative",
        ),
        ("agent.soul.speak.orchestrator.io", SRC / "agent" / "soul" / "speak" / "orchestrator" / "io"),
        (
            "agent.soul.speak.orchestrator.io.inbound",
            SRC / "agent" / "soul" / "speak" / "orchestrator" / "io" / "inbound",
        ),
        (
            "agent.soul.speak.orchestrator.io.inbound.persona",
            SRC / "agent" / "soul" / "speak" / "orchestrator" / "io" / "inbound" / "persona",
        ),
        (
            "agent.soul.speak.orchestrator.io.outbound",
            SRC / "agent" / "soul" / "speak" / "orchestrator" / "io" / "outbound",
        ),
        (
            "agent.soul.speak.orchestrator.io.outbound.persona",
            SRC / "agent" / "soul" / "speak" / "orchestrator" / "io" / "outbound" / "persona",
        ),
    ):
        _ensure_pkg(name, rel)

    _load_module(
        "agent/soul/persona/distill/schema.py",
        "agent.soul.persona.distill.schema",
    )
    _load_module(
        "agent/soul/speak/io/inbound/compose/render.py",
        "agent.soul.speak.io.inbound.compose.render",
    )
    _load_module(
        "agent/soul/speak/llm/engine.py",
        "agent.soul.speak.llm.engine",
    )
    _load_module(
        "agent/soul/voice_rules.py",
        "agent.soul.voice_rules",
    )

    compose_base = "agent.soul.speak.orchestrator.persona.compose"
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
        f"{compose_base}.state",
    )
    _load_module(
        "agent/soul/speak/orchestrator/persona/compose/records.py",
        f"{compose_base}.records",
    )
    _load_module(
        "agent/soul/speak/orchestrator/persona/compose/input.py",
        f"{compose_base}.input",
    )
    _load_module(
        "agent/soul/speak/orchestrator/persona/compose/refine.py",
        f"{compose_base}.refine",
    )
    _load_module(
        "agent/soul/speak/orchestrator/persona/compose/store.py",
        f"{compose_base}.store",
    )

    blocks_base = "agent.soul.speak.orchestrator.persona.blocks"
    for name in ("identity", "presence"):
        _load_module(
            f"agent/soul/speak/orchestrator/persona/blocks/{name}.py",
            f"{blocks_base}.{name}",
        )
    blocks_pkg = sys.modules[blocks_base]
    blocks_pkg.PersonaIdentityBlock = sys.modules[f"{blocks_base}.identity"].PersonaIdentityBlock
    blocks_pkg.PersonaPresenceBlock = sys.modules[f"{blocks_base}.presence"].PersonaPresenceBlock

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
    service = _load_module(
        "agent/soul/speak/orchestrator/persona/compose/service.py",
        f"{compose_base}.service",
    )
    layer = _load_module(
        "agent/soul/speak/orchestrator/persona/layer.py",
        "agent.soul.speak.orchestrator.persona.layer",
    )
    render = _load_module(
        "agent/soul/speak/orchestrator/persona/render.py",
        "agent.soul.speak.orchestrator.persona.render",
    )
    _load_module(
        "agent/soul/speak/orchestrator/io/inbound/persona/request.py",
        "agent.soul.speak.orchestrator.io.inbound.persona.request",
    )
    inbound = _load_module(
        "agent/soul/speak/orchestrator/io/inbound/persona/gateway.py",
        "agent.soul.speak.orchestrator.io.inbound.persona.gateway",
    )
    outbound = _load_module(
        "agent/soul/speak/orchestrator/io/outbound/persona/gateway.py",
        "agent.soul.speak.orchestrator.io.outbound.persona.gateway",
    )
    return service, layer, render, inbound, outbound


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


def _persona_snapshot() -> dict:
    from agent.soul.persona.distill.schema import PERSONA_DISTILL_SCHEMA_VERSION

    return {
        "profile": {"name": "莉奈娅", "core_traits": ["好奇", "温和"], "built": True, "built_at": "test"},
        "self_concept": {"narrative": "我是探险队的记录者。", "beliefs": []},
        "attention_keywords": [],
        "persona_distill": {
            "schema_version": PERSONA_DISTILL_SCHEMA_VERSION,
            "source_revision": "test|",
            "distilled_at": "2026-01-01T00:00:00+00:00",
            "slices": {
                "general": "你是莉奈娅，博物学家，开朗乐观，说话自然。",
                "dialogue": "你是莉奈娅，边境探险队的记录者。你说话不急，习惯先听清对方再开口。",
                "story": "你长期在探险队记录航行与营地夜晚。",
                "reasoning": "你更习惯先搭整体框架，再补细节。",
                "memory_anchor": "你是探险队的记录者，习惯先倾听再整理线索。",
            },
        },
    }


def _presence_snapshot():
    snap = MagicMock()
    snap.session_id = "smoke-persona"
    snap.state.recent_portrait = None
    snap.state.affect.render.return_value = "兴奋但克制"
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.thinking = ""
    snap.state.perception.render.return_value = ""
    return snap


class _PersonaPort:
    def get_persona_snapshot(self, *, session_id: str = "tao") -> dict:
        return _persona_snapshot()


class _PresencePort:
    def snapshot(self, session_id: str):
        return _presence_snapshot()


def _print_blocks(label: str, outbound: object, session_id: str) -> None:
    layer = outbound.build_layer(session_id)
    blocks = layer.render_blocks()
    _sep(f"出站 prompt · persona 子块 · {label}")
    for idx, block in enumerate(blocks, start=1):
        print(f"\n--- block {idx} ---\n{block}", flush=True)
    print(f"\n共 {len(blocks)} 块", flush=True)


def main() -> None:
    service_mod, _layer_mod, _render_mod, inbound_mod, outbound_mod = _bootstrap_persona_modules()
    PersonaComposeService = service_mod.PersonaComposeService
    PersonaComposeRequest = sys.modules[
        "agent.soul.speak.orchestrator.io.inbound.persona.request"
    ].PersonaComposeRequest
    InboundPersonaGateway = inbound_mod.InboundPersonaGateway
    OutboundPersonaGateway = outbound_mod.OutboundPersonaGateway

    session_id = "smoke-persona"
    compose = PersonaComposeService(_PersonaPort(), _PresencePort(), llm=None)
    inbound = InboundPersonaGateway(compose)
    outbound = OutboundPersonaGateway(compose)

    _sep("1) Fallback compose（无 LLM）")
    state = inbound.compose(PersonaComposeRequest(session_id=session_id, turn_index=1))
    print(json.dumps(state.snapshot(), ensure_ascii=False, indent=2), flush=True)
    print(f"version={outbound.version(session_id)}", flush=True)
    _print_blocks("fallback", outbound, session_id)

    cached = inbound.compose(PersonaComposeRequest(session_id=session_id, turn_index=2))
    print(f"\ncache_hit: version unchanged={cached.version == state.version}", flush=True)

    forced = inbound.compose(
        PersonaComposeRequest(session_id=session_id, turn_index=3, force=True)
    )
    print(f"force refresh: v={forced.version}", flush=True)

    llm_cfg = _load_llm_config()
    if llm_cfg is None:
        _sep("2) 真实 LLM · 跳过")
        print("未找到 config/llm_core/config.yaml 或 REACT_TEST_LLM_* 环境变量。", flush=True)
        return

    _sep("2) 真实 LLM · distill_self_narrative")
    from agent.soul.speak.llm.engine import SpeakLLMEngine
    from infra.llm import LLM

    llm_session = f"{session_id}-llm"
    llm_compose = PersonaComposeService(
        _PersonaPort(),
        _PresencePort(),
        llm=SpeakLLMEngine(LLM(llm_cfg)),
    )
    llm_inbound = InboundPersonaGateway(llm_compose)
    llm_outbound = OutboundPersonaGateway(llm_compose)
    llm_state = llm_inbound.compose(
        PersonaComposeRequest(session_id=llm_session, turn_index=1, force=True)
    )
    print(json.dumps(llm_state.snapshot(), ensure_ascii=False, indent=2), flush=True)
    layer = llm_outbound.build_layer(llm_session)
    blocks = layer.render_blocks()
    _sep("出站 prompt · persona 子块 · LLM")
    for idx, block in enumerate(blocks, start=1):
        print(f"\n--- block {idx} ---\n{block}", flush=True)

    _sep("完成")


if __name__ == "__main__":
    main()
