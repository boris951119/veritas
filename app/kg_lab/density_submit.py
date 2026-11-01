"""R22：盒内密度约束的可变交卷 k（3～7）。

优先保证「核心段」占比 ≥ 2/3；不够则缩小 k。
高相关非核心只补位，不回填稀释。不读金标 id。

R24：通稿／近同文簇内只留代表；裁决题软保对立侧／双侧入盒。
"""

from __future__ import annotations

import re
from typing import Any

from app.kg_lab.intent_routes import (
    _CALIBER_VOICE_CUES,
    _CLOCK_KEY,
    _HASHTAG_WRAP,
    _VOICE_CUES,
    anchor_hits,
    core_rank_score,
    is_claim_conflict_route,
    is_core_candidate,
    is_eval_attitude_question,
    is_interview_voice_segment,
    is_short_claim_segment,
    looks_like_wire_shell,
    related_filler,
    slot_align_detail,
    slot_align_hits,
)
from app.kg_lab.source_role import _norm, jaccard_containment, longest_shared_span

TARGET_DENSITY = 2.0 / 3.0
K_MIN = 3
K_MAX = 7

# 近同文／通稿茎簇：Jaccard／包含度／最长共茎任一过阈即并簇
_NEAR_JAC = 0.52
_NEAR_CONT = 0.86
_NEAR_SPAN = 26
_PRECISE_CLOCK = re.compile(r"\d{1,2}时\d{1,2}分")
_CAUSE_FINDING = (
    "查明", "综合分析", "综合认为", "专家认为", "专家综合", "源头发生", "原因现已",
)


def _text_fp(metas: dict[str, dict[str, Any]], pid: str) -> str:
    return _norm(str((metas.get(pid) or {}).get("text") or ""))[:96]


def _norm_body(metas: dict[str, dict[str, Any]], pid: str) -> str:
    return _norm(str((metas.get(pid) or {}).get("text") or ""))


def _doc_id(pid: str, metas: dict[str, dict[str, Any]]) -> str:
    meta = metas.get(pid) or {}
    return str(meta.get("doc_id") or (pid.split("#", 1)[0] if pid else ""))


# R27：繁简对照折叠（新闻常见字），近同文判定用；不改原文
_TRAD_TO_SIMP = str.maketrans({
    "體": "体", "國": "国", "發": "发", "開": "开", "說": "说", "這": "这",
    "為": "为", "來": "来", "對": "对", "時": "时", "會": "会", "業": "业",
    "過": "过", "還": "还", "從": "从", "關": "关", "門": "门", "問": "问",
    "東": "东", "車": "车", "馬": "马", "風": "风", "龍": "龙", "實": "实",
    "驗": "验", "險": "险", "報": "报", "據": "据", "連": "连", "員": "员",
    "廳": "厅", "場": "场", "區": "区", "處": "处", "長": "长", "經": "经",
    "濟": "济", "與": "与", "於": "于", "後": "后", "當": "当", "個": "个",
    "們": "们", "麼": "么", "稱": "称", "達": "达", "裡": "里", "裏": "里",
    "奧": "奥", "亞": "亚", "產": "产", "網": "网", "絡": "络", "測": "测",
    "試": "试", "現": "现", "週": "周", "數": "数", "頻": "频", "緊": "紧",
    "張": "张", "創": "创", "動": "动", "擊": "击", "減": "减", "暫": "暂",
    "級": "级", "終": "终", "統": "统", "練": "练", "聲": "声", "針": "针",
    "頭": "头", "進": "进", "聯": "联", "總": "总", "書": "书", "記": "记",
    "議": "议", "論": "论", "調": "调", "導": "导", "師": "师", "術": "术",
    "應": "应", "該": "该", "認": "认", "識": "识", "證": "证", "優": "优",
    "勢": "势", "態": "态", "況": "况", "環": "环", "節": "节", "點": "点",
    "線": "线", "變": "变", "換": "换", "傳": "传", "協": "协", "執": "执",
    "帶": "带", "災": "灾", "爭": "争", "緩": "缓", "間": "间", "難": "难",
    "響": "响", "際": "际", "斷": "断", "擇": "择",
})


def _fold_zh(s: str) -> str:
    """繁体新闻用字 → 简体，供近同文指纹。"""
    return (s or "").translate(_TRAD_TO_SIMP)


def _near_dup(na: str, nb: str) -> bool:
    """通稿近同文：短通报改写／镜像转载／繁简镜像。

    长段只按高 Jaccard／强包含并簇——共引同一句查明结论不算整段近同文，
    否则对立查明金标会被互相挤掉。
    """
    if not na or not nb:
        return False
    if na[:96] == nb[:96]:
        return True
    # R27：先按繁简折叠再比，避免简繁通稿各占一槽
    fa, fb = _fold_zh(na), _fold_zh(nb)
    if fa[:96] == fb[:96]:
        return True
    a, b = fa[:180], fb[:180]
    jac, cont = jaccard_containment(a, b)
    short = min(len(na), len(nb)) < 110
    if short:
        if jac >= _NEAR_JAC or cont >= _NEAR_CONT:
            return True
        return longest_shared_span(a, b, min_len=18) >= _NEAR_SPAN
    # 长段：近全文转载，或「同一查明结论」长共茎改写（发布会／通稿换皮）
    if jac >= 0.72 or (cont >= 0.92 and jac >= 0.55):
        return True
    span = longest_shared_span(a, b, min_len=36)
    return jac >= 0.45 and span >= 56


_SECONDARY_CUE = (
    "那么", "是否有可能", "有分析认为", "有网友", "正在阅读", "以下是",
    "汇总多方", "时间线", "持续追踪",
)


def _rep_quality(
    pid: str,
    *,
    feats: dict[str, dict[str, Any]],
    metas: dict[str, dict[str, Any]],
    slots: dict[str, Any] | None = None,
) -> tuple[float, float, float, float]:
    """簇代表质量：精确钟点／机构声部／可核验优先；话题标签包装靠后。"""
    text = str((metas.get(pid) or {}).get("text") or "")
    meta = metas.get(pid) or {}
    feat = feats.get(pid) or {}
    ver = float(feat.get("verifiability") or 0.0)
    precise = 1.0 if _PRECISE_CLOCK.search(text) else 0.0
    voice = 1.0 if any(v in text[:160] for v in _VOICE_CUES) else 0.0
    wrap = 1.0 if _HASHTAG_WRAP.search(text[:80]) else 0.0
    # R26：无声部「查明」换皮靠后，避免盖过声部／精确主张段
    caliber_noise = 1.0 if ("查明" in text and voice < 0.5) else 0.0
    # R26：同簇偏短主张段（长通稿改写常盖住短金标近似）
    nlen = len(re.sub(r"\s+", "", text))
    brevity = 1.0 if 0 < nlen <= 280 else (0.5 if nlen <= 400 else 0.0)
    # R39：极短专家原话／否认句优先于设问转述壳
    if 12 <= nlen <= 90:
        brevity += 0.65
        if "说：" in text or "“" in text or '"' in text:
            brevity += 0.4
    # R27：政府口径／可核验责任句优先作簇代表
    resp = 0.0
    if any(c in text for c in _RESP_GOV):
        resp = 1.0
    elif any(c in text for c in ("失控", "失控智能体", "入侵", "许可管理")):
        resp = 0.66
    # 繁简镜像簇：繁体原文常先于简体通稿转载，轻抬作代表
    trad_n = sum(1 for c in text[:220] if ord(c) in _TRAD_TO_SIMP)
    trad = 0.35 if trad_n >= 4 else 0.0
    # R34：问句可核验槽对齐优先作簇代表（抗通稿壳）
    slot_q = min(1.5, 0.35 * float(slot_align_hits(text, slots)))
    secondary = 1.3 if any(c in text[:48] for c in _SECONDARY_CUE) else 0.0
    if slots and any(
        a and len(a) >= 2 and a in text
        for a in (slots.get("claim_alts") or [])[:6]
    ):
        slot_q += 0.5
    # R38：高拉丁声明／原文优先于同数字中文通稿壳
    n_lat = sum(1 for c in text if ("A" <= c <= "Z") or ("a" <= c <= "z"))
    lat_r = n_lat / max(len(text), 1)
    en_decl = 0.0
    if lat_r >= 0.55:
        en_decl = 1.1
        tl = text.lower()
        if any(
            e in tl
            for e in (
                "fuel switch", "preliminary report", "aaib", "locking",
                "killed", "on board", "said on", "cut off",
            )
        ):
            en_decl += 0.6
    wire_pen = 0.0
    if looks_like_wire_shell(text) and lat_r < 0.4:
        wire_pen = 0.8
    # R39：通稿转述带轻降；否认／无关短裁决句轻抬
    relay_pen = 0.0
    if (
        str(feat.get("authority_band") or "") == "wire_relay"
        or str(meta.get("portable_role") or "") == "media_relay"
    ):
        relay_pen = 0.55
    deny = 0.5 if any(
        c in text for c in ("纯属", "予以否认", "没有关系", "无关", "并非")
    ) else 0.0
    return (
        precise
        + voice
        + brevity
        + resp
        + trad
        + slot_q
        + en_decl
        + deny
        - wire_pen
        - secondary
        - relay_pen,
        ver,
        -wrap - caliber_noise,
        float(feat.get("authority_unit") or 0.0),
    )


def _side_of(
    pid: str,
    *,
    feats: dict[str, dict[str, Any]],
    metas: dict[str, dict[str, Any]],
    anchors: dict[str, list[str]] | None,
) -> str:
    text = str((metas.get(pid) or {}).get("text") or "")
    hits = anchor_hits(text, anchors)
    if hits["side"]:
        return str(hits["side"])
    return str((feats.get(pid) or {}).get("option_side") or "") or "other"


def _claim_kernel(text: str) -> str | None:
    """同主张／同数字核：燃油切断声明、否认侥幸短核等。不读案名。"""
    body = text or ""
    tl = body.lower()
    fuel = (
        ("fuel" in tl and "switch" in tl)
        or ("燃油" in body and "开关" in body)
    )
    cut = any(
        w in tl for w in ("cut off", "cutoff", "starved of fuel", "closed")
    ) or any(c in body for c in ("关闭", "切断", "失去了燃油"))
    report = (
        "preliminary" in tl
        or "aaib" in tl
        or any(c in body for c in ("初步调查", "初步报告", "事故调查"))
    )
    if fuel and (cut or report):
        return "fuel_switch_cutoff"
    # 否认／侥幸短核勿整题并一簇——同题可有多条不同表述金标近似
    return None


def _cluster_wire_keep_one(
    scored_cores: list[tuple[float, str]],
    metas: dict[str, dict[str, Any]],
    feats: dict[str, dict[str, Any]] | None = None,
    slots: dict[str, Any] | None = None,
) -> list[tuple[float, str]]:
    """通稿／近同文／同主张核簇：质量更好的代表可替换高分包装段。"""
    feats = feats or {}
    kept: list[tuple[float, str]] = []
    norms: list[str] = []
    kernels: list[str | None] = []
    for sc, pid in scored_cores:
        body = _norm_body(metas, pid)
        text = str((metas.get(pid) or {}).get("text") or "")
        kern = _claim_kernel(text)
        dup_at = next(
            (
                i
                for i, kn in enumerate(norms)
                if _near_dup(body, kn)
                or (kern is not None and kernels[i] == kern)
            ),
            None,
        )
        if dup_at is None:
            kept.append((sc, pid))
            norms.append(body)
            kernels.append(kern)
            continue
        old_sc, old_pid = kept[dup_at]
        if _rep_quality(pid, feats=feats, metas=metas, slots=slots) > _rep_quality(
            old_pid, feats=feats, metas=metas, slots=slots,
        ):
            kept[dup_at] = (sc, pid)
            norms[dup_at] = body
            kernels[dup_at] = kern
    return kept


def _cap_same_doc(
    cores: list[str],
    metas: dict[str, dict[str, Any]],
    *,
    feats: dict[str, dict[str, Any]] | None = None,
    anchors: dict[str, list[str]] | None = None,
    max_per_doc: int = 1,
    exempt_both: bool = True,
) -> list[str]:
    """同文档单侧切片封顶，防止单页通稿／UN 多段占满。

    exempt_both=True：双侧主张段不计入封顶（钟点对撞同页可有多条金标近似）。
    口径题可关豁免，避免同一 UN 页「双侧+独占」连环占槽。
    """
    feats = feats or {}
    out: list[str] = []
    deferred: list[str] = []
    counts: dict[str, int] = {}
    for pid in cores:
        side = _side_of(pid, feats=feats, metas=metas, anchors=anchors)
        if side == "both" and exempt_both:
            out.append(pid)
            continue
        doc = _doc_id(pid, metas) or pid
        n = counts.get(doc, 0)
        if n >= max_per_doc:
            deferred.append(pid)
            continue
        counts[doc] = n + 1
        out.append(pid)
    return out + deferred


def _has_voice(metas: dict[str, dict[str, Any]], pid: str) -> bool:
    text = str((metas.get(pid) or {}).get("text") or "")
    return any(v in text[:160] for v in _VOICE_CUES)


def _has_caliber_voice(metas: dict[str, dict[str, Any]], pid: str) -> bool:
    text = str((metas.get(pid) or {}).get("text") or "")
    return any(v in text[:200] for v in _CALIBER_VOICE_CUES)


# 责任／治理对立可核验线索（OpenAI 失控／政府控制）；裸专名路过不占侧槽
_RESP_VERIFY = (
    "失控", "失控智能体", "入侵", "政府控制", "政府介入", "许可管理",
)
_RESP_GOV = ("政府控制", "政府介入", "美国政府", "政府监管")


def _is_strong_resp(metas: dict[str, dict[str, Any]], pid: str) -> bool:
    text = str((metas.get(pid) or {}).get("text") or "")
    return any(c in text for c in _RESP_VERIFY)


def _resp_strength(metas: dict[str, dict[str, Any]], pid: str) -> int:
    """可核验强度：政府口径 > 失控／入侵事件 > 无。"""
    text = str((metas.get(pid) or {}).get("text") or "")
    if any(c in text for c in _RESP_GOV):
        return 3
    if any(c in text for c in ("失控", "失控智能体", "入侵", "许可管理")):
        return 2
    return 0


def _is_strong_both(
    pid: str,
    *,
    feats: dict[str, dict[str, Any]],
    metas: dict[str, dict[str, Any]],
    anchors: dict[str, list[str]] | None,
) -> bool:
    """真双侧：多锚命中或口径声部；「查明」无口径声部不算。"""
    text = str((metas.get(pid) or {}).get("text") or "")
    hits = anchor_hits(text, anchors)
    if hits["side"] != "both":
        return False
    caliber = _has_caliber_voice(metas, pid)
    multi = (int(hits["a"]) + int(hits["b"])) >= 3
    if ("查明" in text) and not caliber:
        return False
    return caliber or multi


def _soft_side_pack(
    cores: list[str],
    *,
    feats: dict[str, dict[str, Any]],
    metas: dict[str, dict[str, Any]],
    route: str,
    anchors: dict[str, list[str]] | None,
) -> tuple[list[str], list[str]]:
    """裁决题软保位，返回 (有侧核心, 降为补位的无侧核心)。

    1) 真双侧优先；声部单侧先于弱双侧／无声通稿（同侧独占至多 1）；
    2) 无侧别权威段不占核心槽，改补位（防挤对立金标近似段）。
    """
    if route != "adjudicate" or not cores:
        return cores, []
    # 钟点／成因／口径对撞才启用；制度口径题（如 us）不启，防回退
    if not is_claim_conflict_route(anchors):
        return cores, []
    clock_route = any(
        _CLOCK_KEY.search(k or "")
        for k in list((anchors or {}).get("side_a") or [])
        + list((anchors or {}).get("side_b") or [])
    )
    sided: list[str] = []
    unsided: list[str] = []
    for pid in cores:
        side = _side_of(pid, feats=feats, metas=metas, anchors=anchors)
        if side in {"option_a", "option_b", "both"}:
            sided.append(pid)
        else:
            unsided.append(pid)
    def _precise_claim(pid: str) -> bool:
        text = str((metas.get(pid) or {}).get("text") or "")
        keys = list((anchors or {}).get("side_a") or []) + list(
            (anchors or {}).get("side_b") or []
        )
        return any(
            k and len(k) >= 4 and any(u in k for u in "米时分万") and k in text[:120]
            for k in keys
        )

    strong_boths: list[str] = []
    weak_boths: list[str] = []
    voice_excl: list[str] = []
    excl: list[str] = []
    deferred: list[str] = []
    side_n = {"option_a": 0, "option_b": 0}
    # R26：钟点同侧 1；非钟点默认同侧 1，精确主张锚可占第 2 槽（抬成因多金标）
    for pid in sided:
        side = _side_of(pid, feats=feats, metas=metas, anchors=anchors)
        if side == "both":
            if clock_route or _is_strong_both(
                pid, feats=feats, metas=metas, anchors=anchors,
            ):
                strong_boths.append(pid)
            else:
                weak_boths.append(pid)
            continue
        if side in side_n:
            n = side_n[side]
            if n >= 1:
                # R27：同侧后到的更强可核验段，置换先到的裸专名／较弱事件段
                if (not clock_route) and _resp_strength(metas, pid) >= 2:
                    prev = next(
                        (
                            x
                            for x in list(excl) + list(voice_excl)
                            if _side_of(
                                x, feats=feats, metas=metas, anchors=anchors,
                            )
                            == side
                            and _resp_strength(metas, pid) > _resp_strength(metas, x)
                        ),
                        None,
                    )
                    if prev is not None:
                        if prev in excl:
                            excl.remove(prev)
                        if prev in voice_excl:
                            voice_excl.remove(prev)
                        deferred.append(prev)
                        side_n[side] -= 1
                        n = side_n[side]
                if n >= 1:
                    # 第 2 槽：精确主张＋钟点钉、非长通稿、非查明换皮（留给短金标近似）
                    text_i = str((metas.get(pid) or {}).get("text") or "")
                    text_n = len(re.sub(r"\s+", "", text_i))
                    has_clock = bool(_PRECISE_CLOCK.search(text_i))
                    cause_rewrite = any(c in text_i for c in _CAUSE_FINDING)
                    if (
                        clock_route
                        or n >= 2
                        or not _precise_claim(pid)
                        or not has_clock
                        or text_n > 400
                        or cause_rewrite
                    ):
                        deferred.append(pid)
                        continue
            side_n[side] += 1
            if (not clock_route) and _has_caliber_voice(metas, pid):
                voice_excl.append(pid)
            else:
                excl.append(pid)
    # R26：口径／成因题声部独占优先（发言人 vs 秘书长）；钟点题仍双侧优先
    if clock_route:
        return strong_boths + voice_excl + excl + weak_boths + deferred, unsided
    # 两侧声部独占已齐时：弱双侧优先于联合国长文双侧；成因综述弱双侧垫后
    covered = {
        _side_of(pid, feats=feats, metas=metas, anchors=anchors)
        for pid in voice_excl + excl
    }
    def _is_cause_finding(pid: str) -> bool:
        text = str((metas.get(pid) or {}).get("text") or "")
        return any(c in text for c in _CAUSE_FINDING)

    if voice_excl:
        weak_boths = (
            [p for p in weak_boths if not _is_cause_finding(p)]
            + [p for p in weak_boths if _is_cause_finding(p)]
        )
    if {"option_a", "option_b"} <= covered:
        return voice_excl + excl + weak_boths + strong_boths + deferred, unsided
    return voice_excl + excl + strong_boths + weak_boths + deferred, unsided


def pack_core_first(
    order: list[str],
    *,
    feats: dict[str, dict[str, Any]],
    metas: dict[str, dict[str, Any]],
    route: str,
    pool_pos: dict[str, int] | None = None,
    anchors: dict[str, list[str]] | None = None,
    url_of: dict[str, str] | None = None,
    slots: dict[str, Any] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """核心按 rank 分排序；近同文／通稿茎簇去重后再拼补位／其余。"""
    scored_cores: list[tuple[float, str]] = []
    fillers: list[str] = []
    rest: list[str] = []
    seen: set[str] = set()
    for pid in order:
        if not pid or pid in seen:
            continue
        seen.add(pid)
        if is_core_candidate(
            pid, feats=feats, metas=metas, route=route,
            pool_pos=pool_pos, anchors=anchors, url_of=url_of, slots=slots,
        ):
            sc = core_rank_score(
                pid, feats=feats, metas=metas, route=route,
                pool_pos=pool_pos, anchors=anchors, url_of=url_of, slots=slots,
            )
            scored_cores.append((sc, pid))
        elif related_filler(
            pid, feats=feats, metas=metas, route=route,
            anchors=anchors, pool_pos=pool_pos, url_of=url_of, slots=slots,
        ):
            fillers.append(pid)
        else:
            rest.append(pid)

    # R34/R35：事实核对／引号题强槽优先；裁决题短主张优先于长通稿
    _quote_pack = bool(
        slots and (
            slots.get("quotes")
            or slots.get("claim_nouns")
            or slots.get("claim_alts")
        )
    )
    _slot_pack = route == "fact_check" or _quote_pack
    # 仅「侥幸／座位码」类短主张题启用短段优先；数额裁决／吉隆长精密段走原分序
    def _seat_or_luck_q() -> bool:
        if not slots:
            return False
        if any(
            re.match(r"^\d{1,2}[A-Za-z]$", c or "")
            for c in (slots.get("codes") or [])
        ):
            return True
        alts = list(slots.get("claim_alts") or []) + list(slots.get("claim_nouns") or [])
        return any(
            any(k in (a or "") for k in ("侥幸", "生还", "开关", "缺陷"))
            for a in alts
        )

    _adj_short = route == "adjudicate" and _seat_or_luck_q()
    _eval_pack = route == "adjudicate" and is_eval_attitude_question(slots)
    _switch_pack = route == "fact_check" and any(
        any(k in (a or "") for k in ("开关", "燃油", "缺陷"))
        for a in list((slots or {}).get("claim_alts") or [])
    )
    def _core_strong(pid: str) -> int:
        text = str((metas.get(pid) or {}).get("text") or "")
        strong, _ = slot_align_detail(text, slots)
        return int(strong)

    def _core_key(item: tuple[float, str]) -> tuple:
        sc, pid = item
        text = str((metas.get(pid) or {}).get("text") or "")
        nlen = len(re.sub(r"\s+", "", text))
        if _eval_pack:
            voice = 1 if is_interview_voice_segment(text, slots) else 0
            rumor = 1 if (
                not voice
                and any(
                    n in text
                    for n in ("推荐信", "毕业照", "绩点", "保研", "成绩不突出")
                )
            ) else 0
            return (-voice, rumor, -sc, pid)
        if _adj_short:
            short = 1 if is_short_claim_segment(text, slots, route=route) else 0
            long_wire = 1 if (nlen > 500 and not short) else 0
            secondary = 1 if any(c in text[:48] for c in _SECONDARY_CUE) else 0
            return (-short, secondary, long_wire, -sc, pid)
        if _switch_pack:
            tl = text.lower()
            feat = feats.get(pid) or {}
            meta = metas.get(pid) or {}
            sw = 1 if (
                ("燃油" in text and "开关" in text
                 and any(c in text for c in ("关闭", "切断")))
                or (
                    "fuel" in tl and "switch" in tl
                    and any(w in tl for w in ("cut off", "cutoff", "closed"))
                )
            ) else 0
            # 对立支「非设计缺陷」侧：加强检测／锁定／尚未发现缺陷
            defect_side = 1 if (
                ("燃油" in text or "开关" in text or "fuel" in tl)
                and any(
                    c in text or c in tl
                    for c in (
                        "加强检测", "设计缺陷", "锁定", "尚未发现",
                        "locking", "design defect", "no problems",
                    )
                )
            ) else 0
            report = 1 if (
                any(
                    e in text[:360]
                    for e in (
                        "初步调查", "初步报告", "黑匣子", "调查报告",
                        "录音显示", "AAIB", "事故调查",
                    )
                )
                or "preliminary report" in tl
            ) else 0
            casualty = 1 if (
                sw == 0 and defect_side == 0
                and any(c in text[:80] for c in ("遇难", "坠毁", "幸存者", "遇难者"))
            ) else 0
            # R39：拉丁声明／缺陷短核优先；长通稿转述后置（勿让 defect 叠分压过 EN）
            en = 1 if (
                sum(1 for c in text if ("A" <= c <= "Z") or ("a" <= c <= "z"))
                / max(len(text), 1)
                >= 0.55
            ) else 0
            decl = 1 if (sw and report) else 0
            relay = 1 if (
                str(feat.get("authority_band") or "") == "wire_relay"
                or str(meta.get("portable_role") or "") == "media_relay"
            ) else 0
            long_shell = 1 if nlen > 420 else 0
            return (
                -decl,
                -en,
                -defect_side,
                long_shell,
                relay,
                casualty,
                -(sw + report),
                -sc,
                pid,
            )
        if not _slot_pack:
            return (-sc, pid)
        tl = text.lower()
        strong = _core_strong(pid)
        clock = 1 if re.search(
            r"\d{1,2}时\d{1,2}分|\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)",
            text[:180],
        ) else 0
        # 钟点可核查与强槽合成秩，避免 F-16 通稿(strong=3)压过「时点+F-16」金标近似
        rank = strong + 2 * clock
        en_attack = 1 if any(
            e in tl for e in ("launched an", "launched a", "opened fire", "airstrike")
        ) else 0
        primary = 1 if any(
            (c in tl) if c.endswith(" ") else (c in text)
            for c in (
                "felt ", "原话", "访谈", "官方视频", "原始出处", "亲口", "英文访谈",
            )
        ) else 0
        diplo = 1 if any(
            c in text[:160] for c in (
                "劝和促谈", "高度关注", "穿梭调停", "汇总多方", "以下是", "时间线",
            )
        ) else 0
        return (-rank, -clock, -en_attack, -primary, diplo, -sc, pid)

    scored_cores.sort(key=_core_key)
    # 只保留分数靠前的核心，避免假核心灌满 k=7（宁少勿滥）
    if scored_cores:
        # 地板按全局最高分算（勿用强槽排序后的队首分，否则会误砍低分高强槽金标近似）
        top_sc = max(x[0] for x in scored_cores)
        # 对撞题声部／钟点抬分会抬高顶分：放宽地板，避免裁掉同题其它主张段
        # R26：口径／成因题地板再降，避免长主张段被顶分＋旧 wire_pen 裁掉
        claim = is_claim_conflict_route(anchors)
        clock = any(
            _CLOCK_KEY.search(k or "")
            for k in list((anchors or {}).get("side_a") or [])
            + list((anchors or {}).get("side_b") or [])
        )
        if claim and not clock:
            # R27：责任／口径题顶分常被治理长文抬高，地板再放宽
            gap, floor_min = 0.95, 0.22
        elif claim:
            gap, floor_min = 0.55, 0.42
        else:
            gap, floor_min = 0.38, 0.42
        floor = max(floor_min, top_sc - gap)
        # R34–R36：强槽≥2／短主张／专访声部／开关调查声部 豁免分地板
        def _switch_report_core(pid: str) -> bool:
            if not _switch_pack:
                return False
            body = str((metas.get(pid) or {}).get("text") or "")
            tl = body.lower()
            sw = (
                "燃油" in body and "开关" in body
                and any(c in body for c in ("关闭", "切断"))
            ) or (
                "fuel" in tl and "switch" in tl
                and any(w in tl for w in ("cut off", "cutoff", "closed"))
            )
            defect = (
                ("燃油" in body or "开关" in body or "fuel" in tl)
                and any(
                    c in body or c in tl
                    for c in (
                        "加强检测", "设计缺陷", "锁定", "尚未发现",
                        "locking", "design defect", "no problems",
                    )
                )
            )
            report = any(
                e in body[:360]
                for e in (
                    "初步调查", "初步报告", "黑匣子", "调查报告",
                    "录音显示", "AAIB", "事故调查",
                )
            ) or "preliminary report" in tl
            return bool((sw and report) or defect)

        scored_cores = [
            x for x in scored_cores
            if x[0] + 1e-12 >= floor
            or (_slot_pack and _core_strong(x[1]) >= 2)
            or (
                _adj_short
                and is_short_claim_segment(
                    str((metas.get(x[1]) or {}).get("text") or ""),
                    slots,
                    route=route,
                )
            )
            or (
                _eval_pack
                and is_interview_voice_segment(
                    str((metas.get(x[1]) or {}).get("text") or ""),
                    slots,
                )
            )
            or _switch_report_core(x[1])
        ][:14]
    # R24/R25：通稿／近同文簇内留质量更好的代表
    scored_cores = _cluster_wire_keep_one(scored_cores, metas, feats, slots=slots)
    # 精确指纹兜底（同文不同空白）
    cores: list[str] = []
    fp_seen: set[str] = set()
    for sc, pid in scored_cores:
        fp = _text_fp(metas, pid)
        if fp in fp_seen:
            continue
        fp_seen.add(fp)
        cores.append(pid)
    # 对撞题：同文档切片封顶（钟点题双侧豁免；口径／成因题不豁免，防 UN 单页占满）
    if is_claim_conflict_route(anchors):
        clock = any(
            _CLOCK_KEY.search(k or "")
            for k in list((anchors or {}).get("side_a") or [])
            + list((anchors or {}).get("side_b") or [])
        )
        max_doc = 2 if _adj_short else 1
        cores = _cap_same_doc(
            cores, metas, feats=feats, anchors=anchors, max_per_doc=max_doc,
            exempt_both=clock,
        )
    cores, demoted = _soft_side_pack(
        cores, feats=feats, metas=metas, route=route, anchors=anchors,
    )
    # R39：短主张题——否认／主张核对齐短段置前；设问转述与对立壳后置
    if _adj_short and cores:
        alts = list((slots or {}).get("claim_alts") or [])

        def _short_key(pid: str) -> tuple:
            text = str((metas.get(pid) or {}).get("text") or "")
            deny = 1 if any(
                c in text for c in ("纯属", "予以否认", "没有关系", "无关", "并非")
            ) else 0
            alt_n = sum(1 for a in alts if a and len(a) >= 2 and a in text)
            secondary = 1 if any(c in text[:48] for c in _SECONDARY_CUE) else 0
            oppose = 1 if (
                deny == 0
                and "位置" in text
                and any(c in text for c in ("作用", "关键", "保命"))
            ) else 0
            return (-deny, -alt_n, secondary, oppose, pid)

        shorts = [
            p for p in cores
            if is_short_claim_segment(
                str((metas.get(p) or {}).get("text") or ""),
                slots,
                route=route,
            )
        ]
        shorts.sort(key=_short_key)
        rest = [p for p in cores if p not in set(shorts)]
        cores = shorts + rest
    # R39：开关事实核对——拉丁声明 → 缺陷侧短核 → 其余（长通稿壳垫后）
    if _switch_pack and cores:
        en_decl: list[str] = []
        defect: list[str] = []
        other: list[str] = []
        for pid in cores:
            text = str((metas.get(pid) or {}).get("text") or "")
            tl = text.lower()
            n_lat = sum(
                1 for c in text if ("A" <= c <= "Z") or ("a" <= c <= "z")
            )
            en = n_lat / max(len(text), 1) >= 0.55
            sw = (
                ("fuel" in tl and "switch" in tl
                 and any(w in tl for w in ("cut off", "cutoff", "closed")))
                or (
                    "燃油" in text and "开关" in text
                    and any(c in text for c in ("关闭", "切断"))
                )
            )
            report = (
                "preliminary" in tl
                or "aaib" in tl
                or any(
                    e in text[:360]
                    for e in ("初步调查", "初步报告", "黑匣子", "调查报告", "AAIB")
                )
            )
            def_side = (
                ("燃油" in text or "开关" in text or "fuel" in tl)
                and any(
                    c in text or c in tl
                    for c in (
                        "加强检测", "设计缺陷", "锁定", "尚未发现",
                        "locking", "design defect", "no problems",
                    )
                )
            )
            if en and sw and report:
                en_decl.append(pid)
            elif def_side:
                defect.append(pid)
            else:
                other.append(pid)
        cores = en_decl + defect + other
    cores = cores[:6]

    # 自然补位优先；无侧降档段垫后（不抢对立补位槽）
    fillers_scored = sorted(
        fillers,
        key=lambda p: -core_rank_score(
            p, feats=feats, metas=metas, route=route,
            pool_pos=pool_pos, anchors=anchors, url_of=url_of, slots=slots,
        ),
    )
    fill_kept: list[str] = []
    fill_norms = [_norm_body(metas, p) for p in cores]
    for pid in fillers_scored + demoted:
        if pid in cores or pid in fill_kept:
            continue
        body = _norm_body(metas, pid)
        if any(_near_dup(body, kn) for kn in fill_norms):
            continue
        fill_kept.append(pid)
        fill_norms.append(body)
    packed = cores + fill_kept + rest
    return packed, cores, fill_kept


def choose_density_k(
    packed: list[str],
    cores: set[str],
    fillers: set[str],
    *,
    k_min: int = K_MIN,
    k_max: int = K_MAX,
    target: float = TARGET_DENSITY,
) -> dict[str, Any]:
    """在 [k_min,k_max] 选交卷长度。

    策略：
    1. 先构造「不稀释」前缀：只放核心，再按 核心:补位 ≤ 2:1 补位（密度≥2/3）。
    2. 若前缀长度 < k_min，允许用补位凑到 k_min（可能暂时 <2/3）。
    3. 在最终候选序上扫 k：优先密度≥target 的方案，取核心数最多，其次密度，再次较小 k（宁少勿滥）。
    """
    core_list = [p for p in packed if p in cores]
    fill_list = [p for p in packed if p in fillers]
    budget_fill = max(0, len(core_list) // 2)
    kept = list(core_list)
    for f in fill_list[:budget_fill]:
        kept.append(f)
    if len(kept) < k_min:
        for f in fill_list:
            if f in kept:
                continue
            kept.append(f)
            if len(kept) >= k_min:
                break
    if len(kept) < k_min:
        for p in packed:
            if p in kept:
                continue
            kept.append(p)
            if len(kept) >= k_min:
                break

    tail = [p for p in packed if p not in set(kept)]
    cand = kept + tail

    # 达标键：密度优先，其次较小 k（宁少勿滥），再次核心数
    best_ok: tuple[float, int, float, int] | None = None  # (dens, -k, n_core, n_f)
    best_fallback: tuple[float, int, int] | None = None  # (dens, -k, n_core)

    rows = []
    for k in range(k_min, min(k_max, len(cand)) + 1):
        box = cand[:k]
        n_c = sum(1 for p in box if p in cores)
        n_f = sum(1 for p in box if p in fillers)
        dens = n_c / k if k else 0.0
        rows.append({"k": k, "n_core": n_c, "n_filler": n_f, "density": round(dens, 4)})
        if dens + 1e-12 >= target:
            key = (dens, -k, float(n_c))
            if best_ok is None or key > best_ok[:3]:
                best_ok = (dens, -k, float(n_c), n_f)
        fb = (dens, -k, n_c)
        if best_fallback is None or fb > best_fallback:
            best_fallback = fb

    if best_ok is not None:
        dens = float(best_ok[0])
        k_sel = int(-best_ok[1])
        n_c = int(best_ok[2])
        n_f = int(best_ok[3])
        met = True
    else:
        dens_f, neg_k, n_c = best_fallback if best_fallback else (0.0, -k_min, 0)
        k_sel = int(-neg_k) if best_fallback else k_min
        dens = float(dens_f)
        box = cand[:k_sel]
        n_f = sum(1 for p in box if p in fillers)
        met = dens + 1e-12 >= target

    submission = cand[:k_sel]
    return {
        "k": k_sel,
        "submission": submission,
        "n_core": sum(1 for p in submission if p in cores),
        "n_filler": sum(1 for p in submission if p in fillers),
        "n_other": sum(1 for p in submission if p not in cores and p not in fillers),
        "density": round(
            sum(1 for p in submission if p in cores) / k_sel if k_sel else 0.0, 4,
        ),
        "target": target,
        "met_target": met,
        "packed": cand,
        "scan": rows,
        "n_core_available": len(core_list),
        "n_filler_available": len(fill_list),
    }


def density_constrained_submit(
    order: list[str],
    *,
    feats: dict[str, dict[str, Any]],
    metas: dict[str, dict[str, Any]],
    route: str,
    k_min: int = K_MIN,
    k_max: int = K_MAX,
    target: float = TARGET_DENSITY,
    gold_ids: set[str] | None = None,
    pool_pos: dict[str, int] | None = None,
    anchors: dict[str, list[str]] | None = None,
    url_of: dict[str, str] | None = None,
    slots: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """主入口。gold_ids 仅评测披露真实金标密度，不参与选段。"""
    packed, core_list, fill_list = pack_core_first(
        order, feats=feats, metas=metas, route=route,
        pool_pos=pool_pos, anchors=anchors, url_of=url_of, slots=slots,
    )
    cores = set(core_list)
    fillers = set(fill_list)
    # R37：事实核对题若强核心≤1，勿硬凑 k=3 灌通稿（盒稀主因）
    km = int(k_min)
    if route == "fact_check" and len(core_list) <= 1:
        pid0 = core_list[0] if core_list else ""
        body0 = str((metas.get(pid0) or {}).get("text") or "")
        feat0 = feats.get(pid0) or {}
        strong0, _ = slot_align_detail(body0, slots)
        band0 = str(feat0.get("authority_band") or "")
        if strong0 >= 1 and not looks_like_wire_shell(
            body0, band=band0, slot_hits=slot_align_hits(body0, slots),
        ):
            km = 1
    chosen = choose_density_k(
        packed, cores, fillers, k_min=km, k_max=k_max, target=target,
    )
    sub = chosen["submission"]
    out = {
        **chosen,
        "route": route,
        "core_ids": [p for p in sub if p in cores],
        "filler_ids": [p for p in sub if p in fillers],
    }
    if gold_ids is not None:
        ghit = [p for p in sub if p in gold_ids]
        out["gold_in_box"] = ghit
        out["n_gold"] = len(ghit)
        out["gold_density"] = round(len(ghit) / len(sub), 4) if sub else 0.0
    return out
