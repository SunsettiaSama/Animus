"""改写模板：问句框架（带捕获组）+ 低贡献词过滤规则；内置种子 + grown 持久化。

模板消费见 rewriter.TemplateRewriter：
- patterns 依次尝试，首个命中者成为本条查询的模板，捕获组产出实体；
- drop_pos/drop_words/min_term_len 决定切词后的低贡献词丢弃；
- frame 标记问句框架类型（检索 profile 提示，如 recall / quote / topic）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# jieba 词性：助词u 连词c 语气词y 叹词e 非语素x 介词p 代词r 副词d 区别词b
DEFAULT_DROP_POS: frozenset[str] = frozenset({"u", "c", "y", "e", "x", "p", "r", "d", "b"})

# 实体词性前缀：名词族 / 动名词 / 英文专名 / 时间 / 数量
ENTITY_POS_PREFIX: tuple[str, ...] = ("n", "vn", "eng", "m", "q", "t", "s")


@dataclass(frozen=True)
class RewriteTemplate:
    template_id: str
    name: str
    source: str = "builtin"  # builtin | grown
    patterns: tuple[str, ...] = ()
    drop_words: frozenset[str] = field(default_factory=frozenset)
    drop_pos: frozenset[str] = field(default_factory=lambda: DEFAULT_DROP_POS)
    min_term_len: int = 2
    frame: str = "general"  # general | recall | quote | topic | time | verify
    compiled: tuple[re.Pattern, ...] = field(default=())

    def __post_init__(self) -> None:
        if not self.compiled:
            object.__setattr__(
                self, "compiled", tuple(re.compile(p) for p in self.patterns)
            )

    def fingerprint(self) -> frozenset[str]:
        """去重键：pattern 集合归一化。"""
        return frozenset(p.strip() for p in self.patterns)

    def match(self, text: str) -> re.Match | None:
        """首个命中的 pattern 的 Match；无 pattern 或未命中返回 None。"""
        for pattern in self.compiled:
            m = pattern.search(text)
            if m is not None:
                return m
        return None

    def to_dict(self) -> dict:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "source": self.source,
            "patterns": list(self.patterns),
            "drop_words": sorted(self.drop_words),
            "drop_pos": sorted(self.drop_pos),
            "min_term_len": self.min_term_len,
            "frame": self.frame,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RewriteTemplate":
        return cls(
            template_id=str(data.get("template_id") or ""),
            name=str(data.get("name") or ""),
            source=str(data.get("source") or "grown"),
            patterns=tuple(str(p) for p in (data.get("patterns") or [])),
            drop_words=frozenset(str(w) for w in (data.get("drop_words") or [])),
            drop_pos=frozenset(
                str(p) for p in (data.get("drop_pos") or DEFAULT_DROP_POS)
            ),
            min_term_len=int(data.get("min_term_len") or 2),
            frame=str(data.get("frame") or "general"),
        )


# ── 内置种子 ─────────────────────────────────────────────────────────────────
# 通用兜底（无 pattern，永远可用）+ 常见问句框架。捕获组(1)即实体。
# 它们是成长引擎（growth.py）的起点，不求完备——低效模板由 LLM 生成新模板补位。

BUILTIN_TEMPLATES: tuple[RewriteTemplate, ...] = (
    RewriteTemplate(
        template_id="builtin.general",
        name="通用兜底",
        source="builtin",
        frame="general",
    ),
    RewriteTemplate(
        template_id="builtin.remember_q",
        name="回忆问句",
        patterns=(
            r"还记得(.+?)吗",
            r"记不记得(.+)",
            r"想得起来(.+?)吗",
            r"还记得(.+)",
        ),
        frame="recall",
    ),
    RewriteTemplate(
        template_id="builtin.you_said",
        name="转述引用",
        patterns=(
            r"你(?:曾)?(?:说|提)过(?:到)?(.+)",
            r"我(?:曾)?跟你(?:说|提)过(.+)",
        ),
        frame="quote",
    ),
    RewriteTemplate(
        template_id="builtin.tell_me",
        name="话题展开",
        patterns=(r"(?:跟我|和我|给我)(?:说|聊)(?:说|聊)?(?:关于|一下)?(.+)",),
        frame="topic",
    ),
    RewriteTemplate(
        template_id="builtin.last_time",
        name="上次指代",
        patterns=(r"(?:上次|那天|前几?天)(?:我们)?(.+)",),
        frame="time",
    ),
    RewriteTemplate(
        template_id="builtin.how_about",
        name="评价问句",
        patterns=(r"(.+?)怎么样", r"(?:觉得|感觉)(.+?)怎么样?"),
        frame="topic",
    ),
)


class TemplateStore:
    """模板集合：内置在代码，grown 持久化到 json；退役仅对 grown 生效。"""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else None
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._builtin = {t.template_id: t for t in BUILTIN_TEMPLATES}
        self._grown: dict[str, RewriteTemplate] = {}
        self._retired: set[str] = set()
        self._load()

    # ── 读取 ────────────────────────────────────────────────────────────────

    def active_templates(self) -> list[RewriteTemplate]:
        """匹配顺序：带 pattern 的内置 → 带 pattern 的 grown → 通用兜底。"""
        out: list[RewriteTemplate] = []
        for t in self._builtin.values():
            if t.patterns:
                out.append(t)
        for t in self._grown.values():
            if t.patterns and t.template_id not in self._retired:
                out.append(t)
        if "builtin.general" in self._builtin:
            out.append(self._builtin["builtin.general"])
        return out

    def get(self, template_id: str) -> RewriteTemplate | None:
        if template_id in self._builtin:
            return self._builtin[template_id]
        if template_id in self._retired:
            return None
        return self._grown.get(template_id)

    def grown_templates(self) -> list[RewriteTemplate]:
        return [t for tid, t in self._grown.items() if tid not in self._retired]

    # ── 写入 ────────────────────────────────────────────────────────────────

    def add(self, template: RewriteTemplate) -> bool:
        """新增 grown 模板；与现有 pattern 集合重复则拒绝。内置 id 不允许覆盖。"""
        if not template.template_id or template.template_id in self._builtin:
            return False
        fp = template.fingerprint()
        if not fp:
            return False
        for existing in list(self._grown.values()) + list(self._builtin.values()):
            if existing.fingerprint() == fp:
                return False
        self._grown[template.template_id] = template
        self._retired.discard(template.template_id)
        self._persist()
        return True

    def retire(self, template_id: str) -> bool:
        if template_id not in self._grown or template_id in self._retired:
            return False
        self._retired.add(template_id)
        self._persist()
        return True

    # ── 持久化 ──────────────────────────────────────────────────────────────

    def _persist(self) -> None:
        if self._path is None:
            return
        payload = {
            "grown": [t.to_dict() for t in self._grown.values()],
            "retired": sorted(self._retired),
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    def _load(self) -> None:
        if self._path is None or not self._path.is_file():
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for row in payload.get("grown") or []:
            try:
                t = RewriteTemplate.from_dict(row)
            except re.error:
                continue
            if t.template_id and t.template_id not in self._builtin:
                self._grown[t.template_id] = t
        self._retired = {str(x) for x in (payload.get("retired") or [])}
