"""案例装载：cases/<case>/ 目录 → Dossier。

目录布局（推荐带 manifest.yaml，亦可在无 manifest 时裸放文件）::

    cases/solid-state-battery/
    ├── manifest.yaml     # 题目、信源类型与可信度覆盖
    ├── overview.md
    ├── paper_x.pdf
    └── news_y.html

manifest.yaml 示例::

    question: 固态电池路线 2030 年前能否规模上车？
    sources:
      - file: overview.md
        type: report
        credibility: 0.7        # 可选覆盖
        published_at: 2026-03   # 可选：信源时点（时效闸/仲裁新近度用）
      - file: paper_x.pdf
        type: paper
    # 也可整目录推断：未列出的文件按扩展名/文件名推断类型

类型推断兜底：文件名含 paper/patent/news/web/note/report 关键词，
否则按扩展名（.pdf→paper、.html→web、.md/.txt→note）。
未声明 published_at 时回退抽取正文首个「20XX年」落入 meta.year。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.core.evidence import Dossier, Segment, Source, SourceType
from app.ingest.archive import expand_archive, is_archive_file, sniff_format
from app.ingest.links import classify_link_list
from app.ingest.readers import read_any
from app.ingest.segment import split_segments
from app.llm.yaml_robust import load_yaml_robust

_KEYWORD_HINTS: list[tuple[str, SourceType]] = [
    ("paper", SourceType.PAPER),
    ("patent", SourceType.PATENT),
    ("news", SourceType.NEWS),
    ("web", SourceType.WEB),
    ("report", SourceType.REPORT),
    ("note", SourceType.NOTE),
]

_EXT_HINTS = {
    ".pdf": SourceType.PAPER,
    ".html": SourceType.WEB,
    ".htm": SourceType.WEB,
    ".md": SourceType.NOTE,
    ".txt": SourceType.NOTE,
    ".docx": SourceType.REPORT,
    ".xlsx": SourceType.REPORT,
    ".xlsm": SourceType.REPORT,
    ".pptx": SourceType.REPORT,
}

_YEAR_RE = re.compile(r"(19|20)\d{2}\s*年")

# 纯图片文件：无可靠文字层信号，按扩展名识别——专用披露，不入卷
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",
               ".tiff", ".tif", ".heic", ".heif"}


def infer_source_type(path: Path) -> SourceType:
    name = path.name.lower()
    for kw, stype in _KEYWORD_HINTS:
        if kw in name:
            return stype
    return _EXT_HINTS.get(path.suffix.lower(), SourceType.OTHER)


@dataclass
class SourceSpec:
    """单文件的入卷规格（重构 T0：ingest_file 7 参收拢）。

    source_type=None → 按扩展名/文件名推断；preloaded=(title, text)
    已读内容直用（链接清单检测后复用，免双读）；classification 为
    manifest 声明的密级。"""

    source_type: SourceType | None = None
    credibility: float | None = None
    title: str | None = None
    published_at: str | None = None
    classification: str = "internal"
    preloaded: tuple[str, str] | None = None

    @classmethod
    def from_manifest(cls, item: dict) -> "SourceSpec":
        return cls(
            source_type=(SourceType(item["type"])
                         if item.get("type") else None),
            credibility=(float(item["credibility"])
                         if item.get("credibility") is not None else None),
            title=str(item.get("title") or "") or None,
            published_at=(str(item["published_at"])
                          if item.get("published_at") else None),
            classification=str(item.get("classification") or "internal").lower(),
        )


def ingest_file(path: Path, source_id: str, spec: SourceSpec) -> Source:
    """单文件 → Source（切段并编号，locator 记段序）。

    PDF 走可插拔后端（``pdf_backend.extract_pdf``）：Docling 等版式
    引擎产物标 ``derived`` 并默认低可信先验 0.3（manifest 显式
    credibility 仍优先）。
    """
    extract_meta: dict = {}
    if spec.preloaded:
        real_title, text = spec.preloaded
    elif path.suffix.lower() == ".pdf":
        from app.ingest.pdf_backend import extract_pdf

        result = extract_pdf(path)
        real_title, text = result.title, result.text
        extract_meta = dict(result.meta or {})
        extract_meta.setdefault("parser", result.backend)
        if result.fallback_from:
            extract_meta["parser_fallback"] = True
            extract_meta["parser_requested"] = result.fallback_from
        if result.error:
            extract_meta["parser_error"] = result.error
    else:
        real_title, text = read_any(path)
    meta: dict = {"file": str(path), **extract_meta}
    if spec.published_at:
        meta["published_at"] = spec.published_at
    else:
        m = _YEAR_RE.search(text)
        if m:
            meta["year"] = re.sub(r"\D", "", m.group(0))
    source_type = spec.source_type or infer_source_type(path)
    credibility = spec.credibility
    # 版式引擎 / 回退标注的派生解析：与 OCR 同权低可信（除非 manifest 钉死）
    if credibility is None and (
            meta.get("derived") or meta.get("parser") == "docling"):
        credibility = 0.3
    source = Source.create(
        title=spec.title or real_title,
        source_type=source_type,
        credibility=credibility,
        id=source_id,
        meta=meta,
    )
    from app.ingest.text_heal import heal_extracted_text

    text = heal_extracted_text(text)
    for i, seg_text in enumerate(split_segments(text)):
        source.segments.append(Segment(
            id=f"{source_id}#s{i + 1}",
            source_id=source_id,
            text=seg_text,
            locator=f"段 {i + 1}",
            index=i,
        ))
    return source


def _pdf_probe(path: Path) -> dict:
    """PDF 元探测（尽力而为）：页数、内嵌图片数——图片披露用，不炸摄取。"""
    out: dict = {}
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        out["pdf_pages"] = len(reader.pages)
        images = 0
        for page in reader.pages:
            try:
                xo = (page.get("/Resources") or {}).get("/XObject") or {}
                images += sum(
                    1 for k in xo
                    if xo[k].get_object().get("/Subtype") == "/Image")
            except Exception:
                continue
        out["pdf_images"] = images
    except Exception:
        pass
    return out


def _collect_files(case_dir: Path, max_files: int = 500,
                   max_depth: int = 3) -> list[tuple[Path, str]]:
    """有界遍历案例目录 → [(路径, 相对路径)]。

    子目录此前被静默忽略——主办方自己解压成文件夹的场景同样常见；
    隐藏目录与 __pycache__ 跳过，数量/深度封顶（假定输入敌意）。"""
    out: list[tuple[Path, str]] = []

    def _is_artifact_dir(name: str) -> bool:
        # 产物目录（out/out_offline/out_ab_*）与缓存绝不入卷——
        # 自产文件被输入层吃回会形成滚雪球（归一化 diff 验收抓到的
        # 真实回归：72 信源/73218 段，每跑一次演示膨胀一轮）
        return name == "out" or name.startswith("out_") \
            or name in ("history", ".fetched")

    def walk(d: Path, prefix: str, depth: int) -> None:
        if depth > max_depth or len(out) >= max_files:
            return
        for p in sorted(d.iterdir(), key=lambda x: x.name):
            if len(out) >= max_files:
                break
            if depth == 0 and p.name == "manifest.yaml":
                continue
            if p.name.startswith("."):
                continue  # 隐藏文件/目录一律不入卷(.DS_Store/.expected.json 等
                # 系统或工具元数据不是用户内容——macOS 拖目录的真实场景)
            if p.is_dir():
                if p.name == "__pycache__" or _is_artifact_dir(p.name):
                    continue
                walk(p, f"{prefix}{p.name}/", depth + 1)
            else:
                out.append((p, prefix + p.name))

    walk(case_dir, "", 0)
    return out


def load_case(case_dir: Path, fetch_links: bool = False,
              on_file=None) -> Dossier:
    """案例目录 → Dossier（manifest.yaml 用缩进自愈加载）。

    摄取按文件隔离：单个损坏/加密文件只降级为 ingest_notes 披露，
    绝不炸整条 run。目录里的压缩包先安全拆封（slip/炸弹/数量/嵌套
    四道边界，见 ingest.archive），拆出的文件与本地文件同权走本流程；
    链接清单文件默认只披露不抓取（fetch_links=True 才逐条抓取并
    披露成败）。

    on_file: 可选回调 ``(rel, index, total)``，供工作台进度条刷新。
    """
    case_dir = Path(case_dir)
    manifest = {}
    manifest_path = case_dir / "manifest.yaml"
    if manifest_path.is_file():
        manifest = load_yaml_robust(manifest_path)

    dossier = Dossier(
        question=str(manifest.get("question") or case_dir.name),
        title=str(manifest.get("title") or case_dir.name),
    )

    declared_rel: dict[str, dict] = {}
    declared_name: dict[str, dict] = {}
    for item in manifest.get("sources") or []:
        if isinstance(item, dict) and item.get("file"):
            name = str(item["file"])
            declared_rel[name] = item
            declared_name.setdefault(name.rsplit("/", 1)[-1], item)

    counter = 0

    def _next_id() -> str:
        nonlocal counter
        counter += 1
        return f"SRC{counter}"

    def _ingest_one(path: Path, rel: str, spec: SourceSpec) -> None:
        declared_type = spec.source_type
        try:
            source = ingest_file(path, _next_id(), spec)
        except Exception as exc:  # 单文件坏，不炸全场
            dossier.ingest_notes.append({
                "file": rel, "kind": "parse_error",
                "detail": f"解析失败（{type(exc).__name__}: {exc}）——"
                          "该文件内容未进入研判",
            })
            dossier.triage.append({"file": rel, "route": "invalid_parse",
                                   "reason": f"{type(exc).__name__}"})
            return
        if not source.segments:
            detail = "未解析出任何文本"
            if source.meta.get("pdf_pages"):
                detail = (f"疑似扫描件/纯图 PDF（{source.meta['pdf_pages']} 页"
                          f"、{source.meta.get('pdf_images', 0)} 张图）——"
                          "文字层为空，图中数字可能缺失")
            dossier.ingest_notes.append(
                {"file": rel, "kind": "empty", "detail": detail})
            dossier.triage.append({"file": rel, "route": "empty",
                                   "reason": detail[:40]})
            return  # 零段落信源不入卷（已披露）
        if source.meta.get("pdf_images"):
            dossier.ingest_notes.append({
                "file": rel, "kind": "images",
                "detail": f"含 {source.meta['pdf_images']} 张内嵌图片未解析"
                          "——图中的数字与结论可能缺失",
            })
        if spec.classification in ("public", "internal", "confidential"):
            source.classification = spec.classification
        if source.meta.get("parser_fallback") and source.meta.get("parser_error"):
            dossier.ingest_notes.append({
                "file": rel, "kind": "parser_fallback",
                "detail": (
                    f"版式后端失败，已回退 {source.meta.get('parser', 'pypdf')}："
                    f"{source.meta.get('parser_error', '')}"
                ),
            })
        dossier.add_source(source)
        parser = str(source.meta.get("parser") or "")
        if parser == "docling" and not source.meta.get("parser_fallback"):
            route, reason = "layout_parsed", (
                f"{len(source.segments)} 段入卷（Docling 版式解析，派生低可信）"
            )
        else:
            route, reason = "native", (
                f"{len(source.segments)} 段入卷"
                + (f"（类型 {source.source_type.value}）"
                   if declared_type is None else "")
                + (f" · 解析器 {parser}" if parser and parser != "pypdf" else "")
            )
        dossier.triage.append({"file": rel, "route": route, "reason": reason})

    def _handle_links(rel: str, text: str, n_links: int) -> None:
        """链接清单：默认只披露；fetch_links=True 才逐条抓取并披露成败。

        抓取结果落本地缓存（cases/<case>/.fetched/index.json，url→信源
        dict；隐藏目录不被输入遍历捡回）：重跑先查缓存——研判可离线
        确定性重放，不再重复打网关。"""
        if not fetch_links:
            dossier.ingest_notes.append({
                "file": rel, "kind": "links",
                "detail": f"链接清单：含 {n_links} 条网页链接未抓取"
                          "（网络抓取默认关闭，--fetch-links / "
                          "VERITAS_FETCH_LINKS=1 开启）",
            })
            dossier.triage.append({"file": rel, "route": "links_disclosed",
                                   "reason": f"{n_links} 条链接未抓取（默认关）"})
            return
        import hashlib as _hashlib
        import hmac as _hmac
        import json as _json

        from app.ingest.links import LinkFetchError, extract_urls, fetch_link_source

        def _cache_sha256(url: str, body: str) -> str:
            return _hashlib.sha256(f"{url}\n{body}".encode("utf-8")).hexdigest()

        cache_file = case_dir / ".fetched" / "index.json"
        cache: dict[str, dict] = {}
        if cache_file.is_file():
            try:
                loaded = _json.loads(cache_file.read_text(encoding="utf-8"))
                # 投毒防御：每条缓存带内容哈希（url+body），不匹配即弃用
                # 重抓——.fetched 是可写文件，无校验时篡改 JSON 即可向
                # 研判注入任意"已抓取"内容（dev-journal 攻击面 §7）
                for url, rec in (loaded or {}).items():
                    if not isinstance(rec, dict):
                        continue
                    digest = rec.get("_cache_sha256") or ""
                    # 哈希覆盖「重建信源所用的全部字段」的规范化序列化——
                    # 攻击者改任何字段（segments 文本/title/credibility）
                    # 都会使校验失败（只改 _cache_body 不改 segments 无效）
                    canonical = _json.dumps(
                        {k: v for k, v in rec.items()
                         if k != "_cache_sha256"},
                        ensure_ascii=False, sort_keys=True)
                    if not digest or not _hmac.compare_digest(
                            digest, _cache_sha256(url, canonical)):
                        dossier.ingest_notes.append({
                            "file": rel, "kind": "links",
                            "detail": f"缓存条目校验失败，已弃用重抓：{url}",
                        })
                        continue
                    cache[url] = rec
            except (ValueError, OSError):
                cache = {}
        n_ok = n_cached = 0
        failures: list[str] = []
        for url in extract_urls(text):
            if url in cache:
                try:
                    source = Source.from_dict(cache[url])
                    source.id = _next_id()
                    source.meta["cached"] = True
                    dossier.add_source(source)
                    n_cached += 1
                    continue
                except Exception:
                    pass  # 缓存条目损坏 → 视为未命中，重新抓取
            try:
                source = fetch_link_source(url)
                source.id = _next_id()
                dossier.add_source(source)
                n_ok += 1
                # 缓存条目 = 信源 dict + 完整性字段（正文全文+_cache_body,
                # 哈希覆盖 url——防换 url 张冠李戴）
                rec = source.to_dict()
                canonical = _json.dumps(
                    {k: v for k, v in rec.items() if k != "_cache_sha256"},
                    ensure_ascii=False, sort_keys=True)
                rec["_cache_sha256"] = _cache_sha256(url, canonical)
                cache[url] = rec
            except LinkFetchError as exc:
                failures.append(f"{url}（{exc}）")
        if cache:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(
                _json.dumps(cache, ensure_ascii=False, indent=1),
                encoding="utf-8")
        detail = f"链接清单 {rel}：抓取成功 {n_ok} 条"
        if n_cached:
            detail += f"，缓存命中 {n_cached} 条（未重复打网关）"
        if failures:
            sample = "；".join(failures[:3])
            detail += (f"，失败 {len(failures)} 条：{sample}"
                       + ("…" if len(failures) > 3 else ""))
        dossier.ingest_notes.append(
            {"file": rel, "kind": "links", "detail": detail})
        dossier.triage.append({
            "file": rel, "route": "fetched",
            "reason": f"抓取 {n_ok} + 缓存 {n_cached} / 共 {n_links} 条"})

    import tempfile

    def _triage(rel: str, route: str, reason: str) -> None:
        dossier.triage.append({"file": rel, "route": route, "reason": reason})

    def _process_file(path: Path, rel: str, spec: SourceSpec) -> None:
        """单个文件（顶层或压缩包条目）→ 信源或披露，与来源无关同一待遇。"""
        if path.suffix.lower() in _IMAGE_EXTS:
            dossier.ingest_notes.append({
                "file": rel, "kind": "image_file", "path": str(path),
                "detail": "纯图片文件，未做 OCR——图中文字、数字与图表"
                          "信息未进入研判（如有需要请人工整理为文字材料）",
            })
            _triage(rel, "image_disclosed", "图片文件（OCR 开启且网关支持时"
                                            "将转写为低可信派生信源）")
            return
        from app.ingest.readers import UNSUPPORTED_EXTS

        if path.suffix.lower() in UNSUPPORTED_EXTS:
            dossier.ingest_notes.append({
                "file": rel, "kind": "unsupported",
                "detail": f"暂不解析 {path.suffix}（老版 Word/Excel/PPT）——"
                          "请另存为 docx/xlsx/pptx 或导出 PDF/文本后再添加",
            })
            _triage(rel, "unsupported_format", f"格式 {path.suffix}")
            return
        fmt = sniff_format(path) if is_archive_file(path) else ""
        if fmt in ("7z", "rar"):
            dossier.ingest_notes.append({
                "file": rel, "kind": "archive",
                "detail": f"不支持的压缩格式 {fmt}——请解压后提供",
            })
            _triage(rel, "archive_unsupported", f"格式 {fmt}")
            return
        if fmt in ("zip", "tar"):
            entries, notes = expand_archive(
                path, Path(tempfile.mkdtemp(prefix="veritas_unpack_")), label=rel)
            dossier.ingest_notes.extend(notes)
            _triage(rel, "archive_expanded",
                    f"{len(entries)} 个条目拆封后逐条分诊")
            for entry_path, entry_name in entries:
                entry_item = (declared_name.get(
                    entry_name.rsplit("/", 1)[-1]) or {})
                # 溯源：信源来自哪个包的哪个条目
                _process_file(entry_path, f"{rel}::{entry_name}",
                              SourceSpec.from_manifest(entry_item))
            return
        # PDF 必须走可插拔后端（保留 parser/derived meta）；不可 preloaded
        # 旁路——否则 Docling 低可信与 layout_parsed 分诊会丢。
        if path.suffix.lower() == ".pdf":
            _ingest_one(path, rel, spec)
            return
        try:
            title, text = read_any(path)
        except Exception as exc:
            dossier.ingest_notes.append({
                "file": rel, "kind": "parse_error",
                "detail": f"解析失败（{type(exc).__name__}: {exc}）——"
                          "该文件内容未进入研判",
            })
            _triage(rel, "invalid_parse", f"{type(exc).__name__}")
            return
        is_links, n_links = classify_link_list(text)
        if is_links:
            _handle_links(rel, text, n_links)
            return
        from dataclasses import replace as _dc_replace

        _ingest_one(path, rel, _dc_replace(spec, preloaded=(title, text)))

    files = _collect_files(case_dir)
    total = len(files)
    for i, (path, rel) in enumerate(files, 1):
        if on_file is not None:
            try:
                on_file(rel, i, total)
            except Exception:
                pass
        item = declared_rel.get(rel) or declared_name.get(path.name) or {}
        _process_file(path, rel, SourceSpec.from_manifest(item))
    return dossier
