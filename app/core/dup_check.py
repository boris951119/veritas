"""重复与同源检测（零 LLM）：别让「假多源」虚增一致性。

两类陷阱：
- **精确重复**（同一文件改名再传）：SHA-256 全文哈希去重——重复件
  不进分析师提示词（杜绝双重引证推高置信度），在报告披露；
- **近似同源**（十条帖子转同一条谣言）：段落归一化后 2-gram Jaccard
  相似度 ≥ 阈值 → 黄牌「疑似同源转述」——照常进提示词，但一致性
  可能虚高的事实亮给用户。

配对量 O(n²) 只在信源数上，演示与常态语料（≤百份）无压力。
"""

from __future__ import annotations

import hashlib
import zlib
from collections import defaultdict

from app.core.citation_check import normalize
from app.core.evidence import Dossier

_NEAR_DUP_JACCARD = 0.6  # 8字滑窗 Jaccard 0.6+ 意味着六成长句指纹重合——必同源


def _text_of(src) -> str:
    return "\n".join(seg.text for seg in src.segments)


def _shingles(text: str, width: int = 8) -> set[str]:
    """归一化文本 → 字符 shingle 集（滑窗 8，近似长句指纹）。"""
    t = normalize(text)
    if len(t) <= width:
        return {t} if t else set()
    return {t[i:i + width] for i in range(0, len(t) - width + 1, 3)}


def duplicate_map(dossier: Dossier) -> dict[str, str]:
    """精确重复 → {重复件id: 正本id}（每组首件为正本，按信源序）。"""
    seen: dict[str, str] = {}
    out: dict[str, str] = {}
    for src in dossier.sources:
        digest = hashlib.sha256(_text_of(src).encode("utf-8")).hexdigest()
        if digest in seen:
            out[src.id] = seen[digest]
        else:
            seen[digest] = src.id
    return out


def near_dup_pairs(dossier: Dossier) -> list[tuple[str, str, float]]:
    """近似同源信源对 [(a, b, jaccard)]（精确重复对不重复报）。"""
    dups = duplicate_map(dossier)
    infos = [(src.id, _shingles(_text_of(src)))
             for src in dossier.sources if src.id not in dups]
    out: list[tuple[str, str, float]] = []
    for i in range(len(infos)):
        for j in range(i + 1, len(infos)):
            a_id, a_sh = infos[i]
            b_id, b_sh = infos[j]
            union = a_sh | b_sh
            if not union:
                continue
            jac = len(a_sh & b_sh) / len(union)
            if jac >= _NEAR_DUP_JACCARD:
                out.append((a_id, b_id, round(jac, 3)))
    return out


def jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def minhash_signature(text: str, n_perm: int = 32) -> tuple[int, ...]:
    """shingle → MinHash。无主体分桶时给 LSH 用，不替代精确 Jaccard。"""
    shingles = _shingles(text)
    if not shingles:
        return tuple(0 for _ in range(n_perm))
    sig: list[int] = []
    for i in range(n_perm):
        salt = f"{i}:".encode()
        best = min(zlib.crc32(salt + s.encode("utf-8")) for s in shingles)
        sig.append(best)
    return tuple(sig)


def lsh_near_dup_pairs(items: list[tuple[str, str]],
                       *,
                       n_perm: int = 32,
                       bands: int = 8,
                       bucket_cap: int = 64) -> list[tuple[str, str, float]]:
    """近似近重：先按 MinHash 分桶，只对同桶候选算 Jaccard。

    items 为 [(id, text)]。桶过大则截断该桶（漏报优先于 O(n²) 卡死），
    因此这是优化不是完备检测。精确重复由调用方用内容哈希另判。
    """
    if bands < 1 or n_perm % bands != 0:
        raise ValueError("n_perm 必须能被 bands 整除")
    rows = n_perm // bands
    sigs: dict[str, tuple[int, ...]] = {}
    texts: dict[str, str] = {}
    buckets: dict[tuple, list[str]] = defaultdict(list)
    for item_id, text in items:
        sig = minhash_signature(text, n_perm)
        sigs[item_id] = sig
        texts[item_id] = text
        for b in range(bands):
            key = (b, sig[b * rows:(b + 1) * rows])
            buckets[key].append(item_id)
    candidates: set[tuple[str, str]] = set()
    for ids in buckets.values():
        uniq = sorted(set(ids))
        if len(uniq) < 2:
            continue
        if len(uniq) > bucket_cap:
            uniq = uniq[:bucket_cap]
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                a, b = uniq[i], uniq[j]
                candidates.add((a, b) if a < b else (b, a))
    out: list[tuple[str, str, float]] = []
    for a, b in sorted(candidates):
        jac = jaccard(_shingles(texts[a]), _shingles(texts[b]))
        if jac >= _NEAR_DUP_JACCARD:
            out.append((a, b, round(jac, 3)))
    return out


def near_dup_flags(dossier: Dossier) -> list[dict]:
    flags: list[dict] = []
    for a, b, jac in near_dup_pairs(dossier):
        flags.append({
            "kind": "near_dup", "severity": "medium",
            "value": f"{a}~{b}",
            "detail": f"信源 {a} 与 {b} 内容高度重合（Jaccard {jac:.0%}）"
                      "——疑似同源转述，「多源印证」的一致性可能虚高",
        })
    return flags
