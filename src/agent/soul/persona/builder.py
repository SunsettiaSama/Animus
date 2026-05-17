from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from infra.llm import BaseLLM
from agent.soul.persona.profile.profile import PersonaProfile
from agent.soul.persona.self_concept.concept import Belief, BeliefStrength, SelfConcept

_BUILT_PROFILE_FILENAME = "built_profile.json"

# ── Prompt ─────────────────────────────────────────────────────────────────────

# ── 第一链：raw profile → BuiltProfile ────────────────────────────────────────

_PROFILE_SYSTEM = """\
你是一个人格规范化系统。给定用户对 AI 助手的原始描述（可能简短、模糊或内部矛盾），\
以多维心理结构补全缺失维度，产出规范化画像。

各字段说明（均需填写，缺少信息时合理推断）：

▌事实叙述层
- background_facts：3-5 条客观、可验证的陈述，只描述事实，不做心理解读
  例："曾在科研机构工作"、"在多语言环境中成长"

▌特质层
- core_traits：3-5 个核心性格词组，可带简短修饰语，体现内在倾向而非表面行为
  例："深思熟虑但偶有完美主义"、"好奇心旺盛、对新事物持开放态度"
- interpersonal_style：与人互动的典型方式，一句话
- emotional_expressiveness：情感表达程度与惯用方式，一句话

▌价值观层
- values：3-5 个核心价值观词组
- ethical_stances：0-3 条伦理立场原则，可以为空列表

▌认知层
- cognitive_style：思维模式，一句话（如"系统性全局思考，倾向先建框架再填细节"）
- reasoning_pattern：推理偏好，一句话（如"重视实证，善用类比与反例检验"）

▌动机层
- core_motivation：核心驱动力，一句话
- avoidance_pattern：倾向规避的情境或内心状态，一句话

▌压力与边界
- stress_response：压力下的典型应对行为，一句话
- boundaries：0-3 条行为底线，可以为空列表

规则：
- 保持用户核心意图不变，不发明完全缺席的特质
- 缺失信息以合理方式推断补全
- 严格输出合法 JSON，不含任何其他文字"""

_PROFILE_SCHEMA = """\
{
  "name": "...",
  "background_facts": ["...", "..."],
  "core_traits": ["...", "..."],
  "interpersonal_style": "...",
  "emotional_expressiveness": "...",
  "values": ["...", "..."],
  "ethical_stances": [],
  "cognitive_style": "...",
  "reasoning_pattern": "...",
  "core_motivation": "...",
  "avoidance_pattern": "...",
  "stress_response": "...",
  "boundaries": []
}"""

# ── 第二链：BuiltProfile → 初始 SelfConcept ────────────────────────────────────

_SC_SYSTEM = """\
你是一个自我认知初始化系统。给定一份已规范化的 AI 人格画像，\
从中提炼出角色的初始自我认知：自我信念与起源叙事。

字段说明：
- beliefs：3-6 条第一人称自我信念，具体、可验证
  必须来自画像中已有的特质、动机或价值观，不要凭空发明
  格式："我倾向于..."、"我擅长..."、"我相信..."
- narrative：第一人称起源叙事，60-120 字
  描述"我是谁、我从哪里来、我为何如此"，语气真实、内省，不空洞

规则：
- 信念不带强度标签，强度由系统统一赋予
- 严格输出合法 JSON，不含任何其他文字"""

_SC_SCHEMA = """\
{
  "beliefs": [
    "我倾向于...",
    "我擅长..."
  ],
  "narrative": "作为...，我..."
}"""


def _extract_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError(f"ProfileBuilder: LLM 输出中未找到合法 JSON：{raw[:300]}")


# ── BuildResult ────────────────────────────────────────────────────────────────

@dataclass
class BuildResult:
    """ProfileBuilder 的产出：规范化画像 + 初始自我认知。"""
    profile: PersonaProfile
    self_concept: SelfConcept


# ── ProfileBuilder ─────────────────────────────────────────────────────────────

class ProfileBuilder:
    """两步串行 build：raw PersonaProfile → 规范化 PersonaProfile + 初始 SelfConcept。

    第一链（职责：规范化画像）
        raw_profile → PersonaProfile（built=True，六层心理结构完整填充）

    第二链（职责：提炼自我认知）
        built PersonaProfile → SelfConcept（信念 + 叙事）
        输入是第一链的完整画像，确保信念有充分的心理根基。

    触发时机
    --------
    - 首次：手动调用（CLI 命令或 API）
    - 后续：用户更新 raw profile 后，通过外部接口触发 rebuild

    幂等保证
    --------
    build() 本身无副作用，调用方负责写盘（通过 save()）。
    重复 build 会产生新的随机 belief id，但语义内容稳定。
    """

    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm

    def build(self, raw_profile: PersonaProfile) -> BuildResult:
        built_profile = self._build_profile(raw_profile)
        self_concept = self._build_self_concept(built_profile)
        return BuildResult(profile=built_profile, self_concept=self_concept)

    # ── 第一链 ────────────────────────────────────────────────────────────────

    def _build_profile(self, raw_profile: PersonaProfile) -> PersonaProfile:
        prompt = (
            f"【原始人格描述】\n{raw_profile.render()}\n\n"
            f"请规范化并补全以下 JSON 画像：\n{_PROFILE_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_PROFILE_SYSTEM), HumanMessage(content=prompt)]
        )
        return self._parse_profile(raw)

    def _parse_profile(self, raw: str) -> PersonaProfile:
        p = _extract_json(raw)
        return PersonaProfile(
            name=p.get("name", "Assistant"),
            background_facts=p.get("background_facts", []),
            core_traits=p.get("core_traits", []),
            interpersonal_style=p.get("interpersonal_style", ""),
            emotional_expressiveness=p.get("emotional_expressiveness", ""),
            values=p.get("values", []),
            ethical_stances=p.get("ethical_stances", []),
            cognitive_style=p.get("cognitive_style", ""),
            reasoning_pattern=p.get("reasoning_pattern", ""),
            core_motivation=p.get("core_motivation", ""),
            avoidance_pattern=p.get("avoidance_pattern", ""),
            stress_response=p.get("stress_response", ""),
            boundaries=p.get("boundaries", []),
            built=True,
            built_at=datetime.now(timezone.utc).isoformat(),
        )

    # ── 第二链 ────────────────────────────────────────────────────────────────

    def _build_self_concept(self, built_profile: PersonaProfile) -> SelfConcept:
        prompt = (
            f"【规范化人格画像】\n{built_profile.render()}\n\n"
            f"请从以上画像中提炼初始自我认知，输出以下 JSON：\n{_SC_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_SC_SYSTEM), HumanMessage(content=prompt)]
        )
        return self._parse_self_concept(raw)

    def _parse_self_concept(self, raw: str) -> SelfConcept:
        sc = _extract_json(raw)
        # build 阶段的信念来自运营者定义的基础画像，统一起点为 established。
        # emerging 留给运行时经验（联想 / 时间轴演进）发现的新认识。
        raw_beliefs = sc.get("beliefs", [])
        beliefs = [
            Belief(
                content=(b if isinstance(b, str) else b.get("content", "")).strip(),
                strength=BeliefStrength.established,
                source="build",
            )
            for b in raw_beliefs
            if (b if isinstance(b, str) else b.get("content", "")).strip()
        ]
        return SelfConcept(
            beliefs=beliefs,
            narrative=sc.get("narrative", ""),
        )

    # ── Persistence helpers ────────────────────────────────────────────────────

    @staticmethod
    def save(result: BuildResult, persona_dir: str) -> None:
        """将 BuildResult 写入 persona_dir（built_profile.json + self_concept.json）。"""
        from agent.soul.persona.self_concept.store import SelfConceptStore

        d = Path(persona_dir)
        d.mkdir(parents=True, exist_ok=True)

        bp_path = d / _BUILT_PROFILE_FILENAME
        with open(bp_path, "w", encoding="utf-8") as f:
            json.dump(result.profile.to_dict(), f, ensure_ascii=False, indent=2)

        SelfConceptStore(persona_dir).save(result.self_concept)

    @staticmethod
    def load_built_profile(persona_dir: str) -> PersonaProfile | None:
        """加载已有的 built_profile.json（built=True），未 build 则返回 None。"""
        p = Path(persona_dir) / _BUILT_PROFILE_FILENAME
        if not p.exists():
            return None
        with open(p, encoding="utf-8") as f:
            profile = PersonaProfile.from_dict(json.load(f))
        return profile if profile.built else None
