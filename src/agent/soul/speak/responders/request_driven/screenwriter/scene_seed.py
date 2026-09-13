from __future__ import annotations

import math
import random
import re
from typing import Any, Protocol


class _Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


_SPLIT = re.compile(r"[\s,，。！？；;：:\n\r\t、（）()【】\[\]「」『』《》\"'·…]+")
_CJK_CHUNK = re.compile(r"[\u4e00-\u9fff]{2,6}")

# 初始化种子：随机向量 → 近邻词池大小（叙事侧再任选若干组装）
DEFAULT_SCENE_SEED_K = 10

# 系统/席位词：不是镜头物件，禁止进种子与开场旁白
_META_SEEDS = frozenset(
    {
        "智能体",
        "角色",
        "用户",
        "导演",
        "编剧",
        "系统",
        "大纲",
        "旁白",
        "剧情",
        "Soul",
        "soul",
        "Agent",
        "agent",
        "unit",
        "Unit",
    }
)


def is_usable_scene_seed(token: str) -> bool:
    """镜头里能拍到的物件/位置才算种子。"""
    text = str(token or "").strip()
    if len(text) < 2 or len(text) > 8:
        return False
    if text in _META_SEEDS:
        return False
    if any(meta in text for meta in _META_SEEDS if len(meta) >= 2):
        return False
    return True


def extract_candidate_words(text: str, *, limit: int = 64) -> list[str]:
    """从锚定文案抽出可抽样的场景词（简单切分，不做 NER）。"""
    body = str(text or "").strip()
    if not body:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for part in _SPLIT.split(body):
        token = part.strip()
        if len(token) < 2 or len(token) > 12:
            continue
        if token in seen or not is_usable_scene_seed(token):
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= limit:
            return out
    for m in _CJK_CHUNK.finditer(body):
        token = m.group(0)
        if token in seen or not is_usable_scene_seed(token):
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= limit:
            break
    return out


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        fx = float(x)
        fy = float(y)
        dot += fx * fy
        na += fx * fx
        nb += fy * fy
    if na <= 1e-12 or nb <= 1e-12:
        return -1.0
    return dot / math.sqrt(na * nb)


def _uniq_preserve(candidates: list[str]) -> list[str]:
    uniq: list[str] = []
    seen: set[str] = set()
    for w in candidates:
        token = str(w).strip()
        if not token or token in seen:
            continue
        seen.add(token)
        uniq.append(token)
    return uniq


def random_unit_vector(dim: int, *, rng: random.Random | None = None) -> list[float]:
    """随机化单位向量，充当叙事初始化的种子（类似随机数种子）。"""
    d = max(1, int(dim))
    picker = rng if rng is not None else random.Random()
    raw = [picker.gauss(0.0, 1.0) for _ in range(d)]
    norm = math.sqrt(sum(x * x for x in raw))
    if norm <= 1e-12:
        out = [0.0] * d
        out[0] = 1.0
        return out
    return [x / norm for x in raw]


def resolve_embedding_dim(embedder: _Embedder, *, probe: str = "场景") -> int:
    vec = [float(x) for x in embedder.embed(probe)]
    if not vec:
        raise ValueError("embedder returned empty vector")
    return len(vec)


def sample_nearest_to_vector(
    embedder: _Embedder | None,
    *,
    candidates: list[str],
    k: int = DEFAULT_SCENE_SEED_K,
    seed_vector: list[float] | None = None,
    rng: random.Random | None = None,
) -> tuple[list[str], list[float]]:
    """对候选词 embedding，以与种子向量的余弦为权重随机抽 k 个（无放回）。

    返回 (近邻词, 使用的种子向量)。无 embedder 时退化为均匀随机抽 k 词。

    注意不能直接取 cosine top-k：高维下距离集中，随机种子几乎不改变排名，
    每次初始化会得到同一批词（大纲随之同质化）。因此按 softmax(cos/τ)
    加权抽样——与种子方向强相关的词大概率入选，其余在近邻间保持随机，
    每轮初始化给出不同组合。
    """
    uniq = _uniq_preserve(candidates)
    if not uniq:
        return [], list(seed_vector or [])
    top_k = max(1, min(int(k), len(uniq)))
    picker = rng if rng is not None else random.Random()

    if embedder is None:
        if len(uniq) <= top_k:
            return list(uniq), []
        return picker.sample(uniq, top_k), []

    if seed_vector is None:
        dim = resolve_embedding_dim(embedder, probe=uniq[0])
        seed = random_unit_vector(dim, rng=picker)
    else:
        seed = [float(x) for x in seed_vector]
        if not seed:
            dim = resolve_embedding_dim(embedder, probe=uniq[0])
            seed = random_unit_vector(dim, rng=picker)

    scored: list[tuple[float, str]] = []
    for word in uniq:
        w_vec = [float(x) for x in embedder.embed(word)]
        scored.append((_cosine(seed, w_vec), word))
    scored.sort(key=lambda item: item[0], reverse=True)

    tau = 0.08
    items = [w for _, w in scored]
    weights = [math.exp((s - scored[0][0]) / tau) for s, _ in scored]

    picked: list[str] = []
    for _ in range(top_k):
        total = sum(weights)
        if total <= 0:
            picked.extend(items[: top_k - len(picked)])
            break
        r = picker.random() * total
        acc = 0.0
        for idx, wgt in enumerate(weights):
            acc += wgt
            if r <= acc:
                picked.append(items.pop(idx))
                weights.pop(idx)
                break
        else:  # 浮点兜底
            if items:
                picked.append(items.pop(0))
                weights.pop(0)
    return picked, seed


def sample_nearest_words(
    embedder: _Embedder | None,
    *,
    query: str = "",
    candidates: list[str],
    k: int = DEFAULT_SCENE_SEED_K,
    rng: random.Random | None = None,
) -> list[str]:
    """兼容入口：忽略 query，改为随机向量近邻抽样。"""
    del query
    words, _ = sample_nearest_to_vector(
        embedder,
        candidates=candidates,
        k=k,
        rng=rng,
    )
    return words


_VOCAB_WORD_CACHE: dict[int, list[str]] = {}


def extract_vocab_scene_words(embedder: _Embedder, *, limit: int = 2048) -> list[str]:
    """本地 embedding 模型的 tokenizer 词表 → 可用场景词（按词表索引序）。

    词表是全量词空间，不是语料近邻：从这里均匀随机抽词才不会被
    embedding 聚类绑死在同一片语义邻域里。
    """
    key = id(embedder)
    cached = _VOCAB_WORD_CACHE.get(key)
    if cached is not None:
        return cached
    vocab = None
    try:
        client = getattr(embedder, "client", None)
        tokenizer = getattr(client, "tokenizer", None)
        get_vocab = getattr(tokenizer, "get_vocab", None)
        if callable(get_vocab):
            vocab = get_vocab()
    except Exception:
        vocab = None
    words: list[str] = []
    if isinstance(vocab, dict) and vocab:
        for tok in sorted(vocab, key=lambda t: int(vocab.get(t, 0))):
            word = str(tok).replace("##", "").strip()
            if not re.fullmatch(r"[\u4e00-\u9fff]{2,8}", word):
                continue
            if not is_usable_scene_seed(word):
                continue
            words.append(word)
            if len(words) >= limit:
                break
    if words:
        _VOCAB_WORD_CACHE[key] = words
    return words


def sample_random_vocab_words(
    embedder: _Embedder,
    *,
    k: int = DEFAULT_SCENE_SEED_K,
    rng: random.Random | None = None,
) -> list[str]:
    """从 embedding 词表里均匀随机抽 k 个索引词（无放回）。

    效果目标：每次初始化拿到互不相关的词组合，给大纲真正的随机性。
    """
    words = extract_vocab_scene_words(embedder)
    if not words:
        return []
    picker = rng if rng is not None else random.Random()
    return picker.sample(words, min(max(1, int(k)), len(words)))


def build_init_scene_seeds(
    *,
    grounded: str,
    user_text: str = "",
    materials: dict[str, Any] | None = None,
    embedder: _Embedder | None = None,
    k: int = DEFAULT_SCENE_SEED_K,
    rng: random.Random | None = None,
) -> list[str]:
    """初始化场景种子词池：词表均匀随机抽 k（默认 10，可到 20）。

    弃用 embedding 近邻抽样——同语料候选在向量空间是聚类的，
    近邻/softmax 抽出来的词几乎一致，大纲随之同质化。
    有本地模型时从 tokenizer 词表均匀随机抽索引词；没有则退化为
    锚定语料候选词的均匀随机。
    user_text 不参与抽样（避免把用户说法当成种子方向）。
    """
    del user_text
    picker = rng if rng is not None else random.Random()
    if embedder is not None:
        words = sample_random_vocab_words(embedder, k=k, rng=picker)
        if words:
            return words
    corpus_parts = [grounded]
    if materials:
        for key in ("persona_brief", "persona", "interactor_portrait", "dynamic_memory_texts"):
            raw = materials.get(key)
            if isinstance(raw, (list, tuple)):
                clipped = [str(x).strip() for x in raw if str(x).strip()][:6]
                if clipped:
                    corpus_parts.append("\n".join(clipped))
                continue
            text = str(raw or "").strip()
            if text:
                corpus_parts.append(text[:800])
    corpus = "\n".join(p for p in corpus_parts if str(p).strip())
    candidates = extract_candidate_words(corpus, limit=96)
    if not candidates:
        return []
    return picker.sample(candidates, min(max(1, int(k)), len(candidates)))
