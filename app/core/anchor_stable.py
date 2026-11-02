"""C-114：证据定位稳（Q4）— 重构／转存后再解析仍落到 doc_id#para_id。

实验旗 ``VERITAS_ANCHOR_STABLE`` 默认关＝旧行为（严格 content[char_start:char_end]）。
开：ingest 加固（BOM／换行归一、偏移漂移时按段落指纹回绑）＋交卷／台账契约
（引用必须可还原到官方 doc_id＋para_id；失败记 missing_anchor／drift，不静默吞）。

禁：改 BM25／往 pack_material 塞系数／动树15／树17。
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any

from app.core.kg_submit_surface import FORBIDDEN_PACK_KEYS, audit_forbidden_keys

_ENV = "VERITAS_ANCHOR_STABLE"
ACCOUNTING_KEY = "anchor_stable"

# 交卷／台账禁止把这些键当「唯一」定位锚
_FUZZY_ONLY_KEYS = frozenset({"title", "quote", "snippet", "excerpt", "text_only"})


def anchor_stable_enabled(settings: Any | None = None) -> bool:
    """默认关。``VERITAS_ANCHOR_STABLE=1`` 开。"""
    if settings is not None and hasattr(settings, "anchor_stable"):
        return bool(getattr(settings, "anchor_stable"))
    v = (os.environ.get(_ENV) or "").strip().lower()
    if v in ("1", "true", "on", "yes"):
        return True
    if v in ("0", "false", "off", "no"):
        return False
    return False


def text_fingerprint(text: str) -> str:
    """空白归一后的短指纹（比对象、不入提示词）。"""
    norm = re.sub(r"\s+", " ", (text or "").strip())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def normalize_content(content: str) -> tuple[str, list[str]]:
    """轻量归一：去 BOM、CRLF→LF。返回 (正文, 已施变换名)。"""
    mutations: list[str] = []
    out = content or ""
    if out.startswith("\ufeff"):
        out = out.lstrip("\ufeff")
        mutations.append("strip_bom")
    if "\r\n" in out or "\r" in out:
        out = out.replace("\r\n", "\n").replace("\r", "\n")
        mutations.append("crlf_to_lf")
    return out, mutations


def _slice(content: str, start: int, end: int) -> str:
    if start < 0 or end < start:
        return ""
    return content[start:end]


def resolve_paragraph_text(
    content: str,
    para: dict,
    *,
    harden: bool = False,
) -> dict[str, Any]:
    """从一篇文档正文＋段落描述抽出段文本。

    旗关：只做 ``content[char_start:char_end]``（与改前逐字相同）。
    旗开：先归一正文；切片与 ``para["text"]`` 指纹不一致时按指纹回绑；
    仍失败 → ``status=missing_anchor``（调用方须披露，不许当成功）。
    """
    para_id = str((para or {}).get("para_id") or "").strip()
    start = int((para or {}).get("char_start") or 0)
    end = int((para or {}).get("char_end") or 0)
    embedded = str((para or {}).get("text") or "")
    expected_fp = text_fingerprint(embedded) if embedded.strip() else ""

    if not harden:
        text = _slice(content or "", start, end)
        return {
            "para_id": para_id,
            "text": text,
            "char_start": start,
            "char_end": end,
            "status": "ok",
            "mutations": [],
        }

    body, mutations = normalize_content(content or "")
    # BOM 曾使所有偏移 +1：若原文带 BOM 且切片指纹对不上嵌入文，尝试 start-1
    text = _slice(body, start, end)
    status = "ok"

    if expected_fp:
        if text_fingerprint(text) != expected_fp:
            # 1) 尝试未归一原文上的切片（保留旧偏移语义）
            raw_slice = _slice(content or "", start, end)
            if text_fingerprint(raw_slice) == expected_fp:
                text, status = raw_slice, "ok"
            else:
                # 2) 在归一正文里搜唯一指纹原文
                needle = embedded.strip()
                idx = body.find(needle) if needle else -1
                if idx < 0 and needle:
                    # 宽松：压空白后再对位置（仅当唯一）
                    idx = _find_loose(body, needle)
                if idx >= 0:
                    text = body[idx: idx + len(needle)]
                    start, end = idx, idx + len(needle)
                    status = "rebound"
                    mutations = list(mutations) + ["rebind_by_text"]
                else:
                    text = ""
                    status = "missing_anchor"
                    mutations = list(mutations) + ["missing_anchor"]
    elif not text and end > start:
        status = "missing_anchor"
        mutations = list(mutations) + ["missing_anchor"]
    elif embedded.strip() and text_fingerprint(text) != expected_fp:
        status = "drift"
        mutations = list(mutations) + ["drift"]

    return {
        "para_id": para_id,
        "text": text,
        "char_start": start,
        "char_end": end,
        "status": status,
        "mutations": mutations,
        "fingerprint": text_fingerprint(text) if text else "",
    }


def _find_loose(body: str, needle: str) -> int:
    """空白归一后唯一命中时，回原文起点；多命中／零命中 → -1。"""
    norm_body = re.sub(r"\s+", " ", body)
    norm_needle = re.sub(r"\s+", " ", needle.strip())
    if not norm_needle or norm_body.count(norm_needle) != 1:
        return -1
    # 用 needle 首尾短锚在原文定位（保守）
    head = needle.strip()[:12]
    if not head:
        return -1
    positions = []
    start = 0
    while True:
        i = body.find(head, start)
        if i < 0:
            break
        positions.append(i)
        start = i + 1
        if len(positions) > 8:
            return -1
    if len(positions) == 1:
        return positions[0]
    return -1


def validate_citation_anchor(row: dict | None) -> tuple[bool, str]:
    """定位契约：必须同时有非空 doc_id 与 para_id。

    仅标题／全文片段／quote 不能当唯一锚 → (False, reason)。
    """
    if not isinstance(row, dict):
        return False, "not_object"
    doc_id = str(row.get("doc_id") or "").strip()
    para_id = str(row.get("para_id") or "").strip()
    if doc_id and para_id:
        return True, "ok"
    fuzzy = [k for k in _FUZZY_ONLY_KEYS if str(row.get(k) or "").strip()]
    if fuzzy and not (doc_id and para_id):
        return False, f"fuzzy_only:{','.join(fuzzy)}"
    if not doc_id and not para_id:
        return False, "missing_doc_and_para"
    if not doc_id:
        return False, "missing_doc_id"
    return False, "missing_para_id"


def dossier_anchor_map(dossier: Any) -> dict[str, dict[str, Any]]:
    """para_id → {doc_id, fingerprint, text_len}。"""
    out: dict[str, dict[str, Any]] = {}
    for src in getattr(dossier, "sources", None) or []:
        doc_id = str((getattr(src, "meta", None) or {}).get("doc_id")
                     or getattr(src, "id", "") or "")
        for seg in getattr(src, "segments", None) or []:
            pid = str(getattr(seg, "id", "") or "")
            if not pid:
                continue
            text = str(getattr(seg, "text", "") or "")
            out[pid] = {
                "doc_id": doc_id,
                "para_id": pid,
                "fingerprint": text_fingerprint(text),
                "text_len": len(text),
            }
    return out


def compare_anchor_maps(
    baseline: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
    keys: list[str] | None = None,
) -> dict[str, Any]:
    """重构前后定位键一致率。keys 缺省＝baseline 全键。"""
    targets = list(keys) if keys is not None else sorted(baseline.keys())
    ok = 0
    missing: list[str] = []
    drift: list[str] = []
    for pid in targets:
        b = baseline.get(pid)
        c = current.get(pid)
        if b is None:
            continue
        if c is None:
            missing.append(pid)
            continue
        if (b.get("doc_id") == c.get("doc_id")
                and b.get("fingerprint") == c.get("fingerprint")
                and b.get("fingerprint")):
            ok += 1
        else:
            drift.append(pid)
    n = len(targets) if targets else 0
    rate = (ok / n) if n else 0.0
    return {
        "n": n,
        "ok": ok,
        "missing_anchor": missing,
        "drift": drift,
        "consistency_rate": rate,
    }


def apply_ingest_anchor_accounting(
    dossier: Any,
    *,
    n_ok: int,
    n_rebound: int,
    n_missing: int,
    n_drift: int,
    samples: list[dict] | None = None,
) -> dict[str, Any]:
    """写入 accounting[anchor_stable]；返回同一对象供审计。"""
    payload = {
        "enabled": True,
        "n_ok": int(n_ok),
        "n_rebound": int(n_rebound),
        "n_missing_anchor": int(n_missing),
        "n_drift": int(n_drift),
        "samples": list(samples or [])[:12],
    }
    # 禁系数键
    bad = audit_forbidden_keys(payload)
    if bad:
        raise ValueError(f"anchor_stable payload hits forbidden: {bad}")
    for k in FORBIDDEN_PACK_KEYS:
        if k in payload:
            raise ValueError(f"forbidden pack key in anchor_stable: {k}")
    acc = getattr(dossier, "accounting", None)
    if acc is None:
        dossier.accounting = {}
        acc = dossier.accounting
    acc[ACCOUNTING_KEY] = payload
    return payload


def audit_fact_anchors(facts: list[dict] | None) -> dict[str, Any]:
    """对提交／金标事实表跑定位契约；缺锚列入 missing_anchor。"""
    missing: list[dict] = []
    ok = 0
    for row in facts or []:
        good, reason = validate_citation_anchor(row)
        if good:
            ok += 1
        else:
            missing.append({
                "doc_id": str((row or {}).get("doc_id") or ""),
                "para_id": str((row or {}).get("para_id") or ""),
                "reason": reason,
            })
    return {
        "n": ok + len(missing),
        "ok": ok,
        "missing_anchor": missing,
    }
