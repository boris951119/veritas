"""FastAPI 可视化工作台。

把研判产物（cases/<case>/out*/report.json + chain.jsonl）变成可交互的
工作台：证据图三级下钻、置信度分量面板、冲突清单、少数意见、引文打回
记录、哈希链校验与「改一字即红」篡改演示。

人工修改即研判的一部分：删证据 / 调权重 / 调信源可信度都走
confidence.recompute_all 同一入口重算，并把 human 事件追加进哈希链
（修改可审计、链仍自洽）——这正是榜单硬需求 5 的「人工修改后重新计算」。

只读端点零副作用；变更端点落盘回 report.json / chain.jsonl。默认只绑
127.0.0.1。启动：python -m app.server [--port 8765]
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.agents.chair import refresh_synthesis_after_human
from app.core.audit import audit_all, summarize
from app.core.confidence import recompute_all
from app.core.evidence import Dossier
from app.core.hashchain import HashChain
from app.core.human_ops import edit_conclusion, override_resolution
from app.core.reasoning_graph import build_reasoning_graph
from app.core.skills import skill_status

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEB_DIR = _REPO_ROOT / "web"
# 首次人工修改前的原始产物快照（重置端点的还原点；随 out* 一起被
# 打包脚本排除，不进携带包）
_PRISTINE_REPORT = "report.pristine.json"
_PRISTINE_CHAIN = "chain.pristine.jsonl"


def _cases_root(cases_root: Path | None) -> Path:
    return cases_root or (_REPO_ROOT / "cases")


def _case_dir(cases_root: Path | None, case: str) -> Path:
    """案例目录必须落在 cases/ 下，拒绝 .. / 绝对路径 / 分隔符。"""
    root = _cases_root(cases_root).resolve()
    name = str(case or "").strip()
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise HTTPException(400, "非法案例名")
    base = (root / name).resolve()
    try:
        base.relative_to(root)
    except ValueError as exc:
        raise HTTPException(400, "非法案例名") from exc
    return base


def _find_out_dir(cases_root: Path | None, case: str) -> Path:
    base = _case_dir(cases_root, case)
    if not base.is_dir():
        raise HTTPException(404, f"案例不存在: {case}")
    for sub in ("out", "out_offline"):
        p = base / sub
        if (p / "report.json").is_file():
            return p
    raise HTTPException(404, f"案例 {case} 无研判产物（先跑 pipeline 或 demo_offline）")


def _safe_out_dir(cases_root: Path | None, case: str,
                  out: str | None = None) -> Path:
    """只允许 out / out_offline / history/<id>，拒绝路径穿越。"""
    if not out:
        return _find_out_dir(cases_root, case)
    base = _case_dir(cases_root, case)
    if not base.is_dir():
        raise HTTPException(404, f"案例不存在: {case}")
    rel = str(out).replace("\\", "/").strip("/")
    parts = [p for p in rel.split("/") if p]
    if (not parts or any(p in (".", "..") for p in parts)
            or parts[0] not in ("out", "out_offline", "history")):
        raise HTTPException(400, "非法产物路径")
    if parts[0] == "history":
        if len(parts) != 2:
            raise HTTPException(400, "非法产物路径")
    elif len(parts) != 1:
        raise HTTPException(400, "非法产物路径")
    path = (base / "/".join(parts)).resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise HTTPException(400, "非法产物路径") from exc
    if not (path / "report.json").is_file():
        raise HTTPException(404, "该记录没有报告")
    return path


def _peek_question(report: Path) -> str:
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
        return str(data.get("question") or "")
    except (OSError, json.JSONDecodeError, TypeError):
        return ""


def _list_history(cases_root: Path | None) -> dict:
    from app.workbench_run import case_question

    examples = []
    runs = []
    root = _cases_root(cases_root)
    if not root.is_dir():
        return {"examples": examples, "runs": runs}
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        if not (d / "manifest.yaml").is_file():
            continue
        latest = ""
        for sub in ("out", "out_offline"):
            if (d / sub / "report.json").is_file():
                latest = sub
                break
        examples.append({
            "name": d.name,
            "out": latest,
            "has_result": bool(latest),
            "question": case_question(d),
            "n_files": sum(1 for p in d.iterdir()
                           if p.is_file() and p.name != "manifest.yaml"),
        })
        hist = d / "history"
        if not hist.is_dir():
            continue
        for slot in hist.iterdir():
            report = slot / "report.json"
            if not slot.is_dir() or not report.is_file():
                continue
            runs.append({
                "case": d.name,
                "out": f"history/{slot.name}",
                "id": slot.name,
                "question": _peek_question(report),
                "mtime": report.stat().st_mtime,
            })
    runs.sort(key=lambda r: r["mtime"], reverse=True)
    return {"examples": examples, "runs": runs}


def _ingest_payload(case_dir: Path) -> dict:
    from app.config import Settings
    from app.ingest.case_loader import load_case
    from app.ingest.pdf_backend import set_pdf_backend
    from app.ingest.triage import ROUTE_LABEL

    set_pdf_backend(Settings.from_env().pdf_backend)
    d = load_case(case_dir)
    return {
        "case": case_dir.name,
        "question": d.question,
        "n_sources": len(d.sources),
        "n_segments": sum(len(s.segments) for s in d.sources),
        "triage": [{**r, "label": ROUTE_LABEL.get(r.get("route"), r.get("route"))}
                   for r in d.triage],
    }


def _load_pair(out_dir: Path) -> tuple[Dossier, HashChain]:
    dossier = Dossier.from_json(out_dir / "report.json")
    chain_path = out_dir / "chain.jsonl"
    chain = (HashChain.from_jsonl(chain_path) if chain_path.is_file()
             else HashChain())
    return dossier, chain


def _dossier_payload(out_dir: Path, clearance: str = "confidential") -> dict:
    from app.core.view_filter import redact_dossier

    dossier, chain = _load_pair(out_dir)
    verify = chain.verify_chain()
    # 权限视图：过滤只发生在展示层（低权限不借审计泄露涉密内容）；
    # 机械核对警示在所服务的视图上即时重算——人工修改与文件篡改都
    # 逃不过下一次读取（「改数字即红」的工作台侧实现）
    view, _stats = redact_dossier(dossier, clearance)
    flags = audit_all(view)
    return {
        "case": out_dir.parent.name,
        "out_dir": out_dir.name,
        "dossier": view.to_dict(),
        "audit": {"flags": flags, **summarize(flags),
                  "skills": skill_status(view)},
        "accounting": dict(dossier.accounting or {}),
        "timeline": [
            {"index": r.index, "ts": r.ts, "actor": r.actor, "event": r.event}
            for r in chain.records
        ],
        "chain": {
            "n_records": len(chain.records),
            "ok": verify.ok,
            "bad_index": verify.bad_index,
            "reason": verify.reason,
            "signed": verify.signed,
        },
    }


def _ensure_pristine(out_dir: Path) -> None:
    """首次人工修改前快照管线原始产物（幂等，后续修改不再覆盖快照）。"""
    if (out_dir / _PRISTINE_REPORT).is_file():
        return
    shutil.copy2(out_dir / "report.json", out_dir / _PRISTINE_REPORT)
    chain_path = out_dir / "chain.jsonl"
    if chain_path.is_file():
        shutil.copy2(chain_path, out_dir / _PRISTINE_CHAIN)


def _mutate(cases_root: Path | None, case: str, event: str,
            payload: dict, mutate_fn) -> dict:
    """变更端点公共骨架：改 → 重算 → 哈希链留痕 → 落盘 → 回最新全量。

    mutate_fn 可返回 dict——并入链事件 payload（审计计数等）并随响应
    回传（resp["op"]），供前端提示「本次修改新引入了什么」。"""
    out_dir = _find_out_dir(cases_root, case)
    dossier, chain = _load_pair(out_dir)
    _ensure_pristine(out_dir)
    extra = mutate_fn(dossier)
    recompute_all(dossier, n_panel=max(1, len(dossier.panel)))
    refresh_synthesis_after_human(dossier)
    chain.append(event, "human", {**payload, **(extra or {})})
    dossier.to_json(out_dir / "report.json")
    chain.to_jsonl(out_dir / "chain.jsonl")
    result = _dossier_payload(out_dir)
    if extra:
        result["op"] = extra
    return result



class RunReq(BaseModel):
    case: str
    question: str = ""
    background: bool = False


class CancelReq(BaseModel):
    case: str
    run_id: str = ""


class EvidenceWeightReq(BaseModel):
    case: str
    evidence_id: str
    weight: float


class EvidenceRemoveReq(BaseModel):
    case: str
    evidence_id: str


class EvidenceRelationReq(BaseModel):
    case: str
    evidence_id: str
    relation: str  # causation | correlation | expert_judgment


class CredibilityReq(BaseModel):
    case: str
    source_id: str
    credibility: float


class RelevanceOverrideReq(BaseModel):
    case: str
    source_id: str
    override: str  # include / exclude / ""（恢复自动）


class ConclusionEditReq(BaseModel):
    case: str
    conclusion_id: str
    statement: str


class ConflictOverrideReq(BaseModel):
    case: str
    conflict_id: str
    winner_id: str


class CaseResetReq(BaseModel):
    case: str


class CaseRenameReq(BaseModel):
    case: str
    title: str


class CaseFilesRemoveReq(BaseModel):
    case: str
    files: list[str]


class LlmSettingsReq(BaseModel):
    api_key: str | None = None  # None=不改；""=清除
    base_url: str | None = None
    model: str | None = None  # 兼容旧字段；可与 models 二选一
    models: list[str] | str | None = None  # 多模型：列表或换行/逗号文本
    hetero: bool | None = None  # 多模型时是否按角色轮转
    force_demo: bool | None = None


def create_app(cases_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="veritas 工作台", docs_url=None, redoc_url=None)

    @app.get("/")
    def index() -> FileResponse:
        # 工作台常改 UI，禁止浏览器死缓存旧 JS（否则勾选/删除会「看不见」）
        return FileResponse(
            _WEB_DIR / "index.html",
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    @app.get("/api/cases")
    def list_cases() -> dict:
        from app.ingest.case_loader import _collect_files
        from app.llm.yaml_robust import load_yaml_robust
        from app.workbench_run import case_question

        cases = []
        root = _cases_root(cases_root)
        if not root.is_dir():
            return {"cases": []}
        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            if not (d / "manifest.yaml").is_file():
                continue
            out_dir = ""
            for sub in ("out", "out_offline"):
                if (d / sub / "report.json").is_file():
                    out_dir = sub
                    break
            n_files = len(_collect_files(d))
            man = load_yaml_robust(d / "manifest.yaml") or {}
            imported = bool(man.get("imported")) or d.name.startswith("user-")
            try:
                featured = int(man.get("featured") or 0)
            except (TypeError, ValueError):
                featured = 0
            cases.append({
                "name": d.name,
                "out_dir": out_dir or "out_offline",
                "has_result": bool(out_dir),
                "question": case_question(d),
                "n_files": n_files,
                "imported": imported,
                "title": str(man.get("title") or d.name),
                "featured": featured,
                "blurb": str(man.get("blurb") or ""),
            })
        # 主演示（featured 高）置顶，其余按名
        cases.sort(key=lambda c: (-int(c.get("featured") or 0), c["name"]))
        return {"cases": cases}

    @app.post("/api/run")
    def run_now(req: RunReq) -> dict:
        """工作台主按钮：选好议题后立刻研判（演示桩，秒级，不耗密钥）。"""
        from app.workbench_run import run_workbench_case

        case_dir = _cases_root(cases_root) / req.case
        if not case_dir.is_dir() or not (case_dir / "manifest.yaml").is_file():
            raise HTTPException(404, "找不到这套资料")
        from app.config import Settings
        from app.ingest.case_loader import load_case
        from app.ingest.pdf_backend import set_pdf_backend
        set_pdf_backend(Settings.from_env().pdf_backend)
        preview = load_case(case_dir)
        if not preview.sources:
            raise HTTPException(
                422, "分诊后没有可研判的文本。图片和老版 Word 不会当正文入卷，"
                     "请补充 PDF、docx、xlsx 或文本后再研判。")
        from app.workbench_llm import llm_status

        if req.background:
            import threading
            from app.workbench_run import new_run_id

            rid = new_run_id()

            def _job() -> None:
                try:
                    run_workbench_case(case_dir, question=req.question, run_id=rid)
                except Exception:
                    return

            threading.Thread(target=_job, name=f"veritas-{rid}", daemon=True).start()
            return {
                "ok": True,
                "run_id": rid,
                "out": f"history/{rid}",
                "status": "running",
            }

        try:
            out_dir = run_workbench_case(case_dir, question=req.question)
        except Exception as exc:
            from app.llm.budget import TaskCancelledError

            if isinstance(exc, TaskCancelledError):
                raise HTTPException(409, "研判已终止") from exc
            msg = str(exc)
            # 网关拒模型时别把整段 traceback 甩成「请求未完成」
            if "Access to model denied" in msg or "model denied" in msg.lower():
                raise HTTPException(
                    502,
                    "当前网关拒绝了所选模型（Access denied）。"
                    "请点右上角「模型接入」换一个有权限的模型 ID，或勾选"
                    "「即使有密钥也强制用演示桩」先走通流程。",
                ) from exc
            if "全部分析师研判失败" in msg or "LLM 调用失败" in msg:
                short = msg
                if len(short) > 220:
                    short = short[:220] + "…"
                raise HTTPException(502, f"研判未完成：{short}") from exc
            raise
        payload = _dossier_payload(out_dir)
        payload["workbench_mode"] = llm_status()["mode"]
        return payload

    @app.post("/api/cancel")
    def cancel_run(req: CancelReq) -> dict:
        """终止当前案例正在跑的研判（协作式：下一 LLM 检查点生效）。"""
        from app.core.run_cancel import is_cancelled, request_cancel

        case_dir = _case_dir(cases_root, req.case)
        if not case_dir.is_dir():
            raise HTTPException(404, "找不到这套资料")
        rid = (req.run_id or "").strip() or None
        ok = request_cancel(req.case, rid)
        return {
            "ok": True,
            "accepted": ok,
            "cancelled": is_cancelled(req.case, rid),
            "detail": ("已发出终止信号，将在当前模型调用结束后停下"
                       if ok else "当前没有进行中的研判"),
        }

    @app.get("/api/ingest")
    def ingest_preview(case: str) -> dict:
        """添加资料后立刻看分诊账本（零 LLM）：每份文件怎么入卷、为何跳过。"""
        case_dir = _case_dir(cases_root, case)
        if not case_dir.is_dir() or not (case_dir / "manifest.yaml").is_file():
            raise HTTPException(404, "找不到这套资料")
        return _ingest_payload(case_dir)

    @app.post("/api/case/import")
    async def import_case(
        files: list[UploadFile] = File(...),
        question: str = Form(""),
        case: str = Form(""),
    ) -> dict:
        """工作台添加文件夹/散文件：落盘后立刻分诊切片。

        若带 case=已有导入案，则追加到该案（删错再补）；否则新建 user-*。
        """
        from app.ingest.import_case import (
            CaseImportError, append_imported_files, write_imported_case,
        )
        from app.llm.yaml_robust import load_yaml_robust

        blobs: list[tuple[str, bytes]] = []
        for uf in files:
            blobs.append((uf.filename or "unnamed", await uf.read()))
        root = _cases_root(cases_root)
        try:
            if case:
                case_dir = root / case
                man = case_dir / "manifest.yaml"
                if not case_dir.is_dir() or not man.is_file():
                    raise HTTPException(404, "找不到这套资料")
                meta_man = dict(load_yaml_robust(man) or {})
                if not (meta_man.get("imported") or case.startswith("user-")):
                    raise HTTPException(422, "示例案卷不能往里加文件，请新建一套")
                meta = append_imported_files(case_dir, blobs)
                if question.strip():
                    # 议题栏有字时同步进 manifest（追加场景）
                    import yaml
                    meta_man["question"] = question.strip()
                    man.write_text(
                        yaml.safe_dump(meta_man, allow_unicode=True,
                                       sort_keys=False),
                        encoding="utf-8",
                    )
                    meta["question"] = question.strip()
            else:
                meta = write_imported_case(root, blobs, question)
        except CaseImportError as exc:
            raise HTTPException(422, str(exc)) from exc
        payload = _ingest_payload(root / meta["case"])
        return {**meta, **payload}

    @app.post("/api/case/files/remove")
    def remove_case_files_api(req: CaseFilesRemoveReq) -> dict:
        """分诊清单勾选删除错导文件；仅导入案（imported / user-*）。"""
        from app.ingest.import_case import CaseImportError, remove_case_files
        from app.llm.yaml_robust import load_yaml_robust

        if not req.files:
            raise HTTPException(422, "请先勾选要删除的文件")
        case_dir = _cases_root(cases_root) / req.case
        man = case_dir / "manifest.yaml"
        if not case_dir.is_dir() or not man.is_file():
            raise HTTPException(404, "找不到这套资料")
        meta = dict(load_yaml_robust(man) or {})
        if not (meta.get("imported") or req.case.startswith("user-")):
            raise HTTPException(422, "示例案卷不能删文件")
        try:
            result = remove_case_files(case_dir, req.files)
        except CaseImportError as exc:
            raise HTTPException(422, str(exc)) from exc
        payload = _ingest_payload(case_dir)
        return {**result, **payload}

    @app.get("/api/llm")
    def get_llm_settings() -> dict:
        """工作台模型接入状态（key 只回掩码）。"""
        from app.workbench_llm import apply_to_environ, llm_status

        apply_to_environ()
        return llm_status()

    @app.post("/api/llm")
    def save_llm_settings_api(req: LlmSettingsReq) -> dict:
        """页面接入 API Key / 网关 / 模型；落盘本机且不进 git。"""
        from app.workbench_llm import save_llm_settings

        return save_llm_settings(
            api_key=req.api_key,
            base_url=req.base_url,
            model=req.model,
            models=req.models,
            hetero=req.hetero,
            force_demo=req.force_demo,
        )

    @app.post("/api/llm/exit-keep")
    def llm_exit_keep() -> dict:
        """退出时「确定」：保留当前 API Key，下次启动无需再填。"""
        from app.workbench_llm import keep_session_key

        return keep_session_key()

    @app.post("/api/llm/exit-discard")
    def llm_exit_discard() -> dict:
        """退出时「不保存」：删除当次使用的 API Key。"""
        from app.workbench_llm import discard_session_key

        return discard_session_key()

    @app.post("/api/case/rename")
    def rename_case(req: CaseRenameReq) -> dict:
        """改案件显示名（只改 manifest.title，不改目录名）。"""
        import yaml
        from app.llm.yaml_robust import load_yaml_robust

        title = (req.title or "").strip()
        if not title:
            raise HTTPException(422, "案件名不能为空")
        if len(title) > 80:
            raise HTTPException(422, "案件名太长")
        case_dir = _cases_root(cases_root) / req.case
        man_path = case_dir / "manifest.yaml"
        if not case_dir.is_dir() or not man_path.is_file():
            raise HTTPException(404, "找不到这套资料")
        man = dict(load_yaml_robust(man_path) or {})
        man["title"] = title
        man_path.write_text(
            yaml.safe_dump(man, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return {"case": req.case, "title": title}

    @app.get("/api/history")
    def get_history() -> dict:
        """示例案卷 + 工作台做过的跑次（history/ 快照）。"""
        return _list_history(cases_root)

    @app.get("/api/dossier")
    def get_dossier(case: str, clearance: str = "confidential",
                    out: str | None = None) -> dict:
        """权限视图：clearance ∈ public/internal/confidential（默认本机
        操作员全量）。过滤只发生在展示视图，链与原始案卷全量保真。
        out 可选：out / out_offline / history/<id>。"""
        return _dossier_payload(_safe_out_dir(cases_root, case, out), clearance)

    @app.get("/api/progress")
    def get_progress(case: str, out: str | None = None) -> dict:
        """当前/最后步骤（跑到一半评委喊停可看）。

        不要求 report.json 已落盘——开跑瞬间只有 progress.json。
        """
        base = _case_dir(cases_root, case)
        if not base.is_dir():
            raise HTTPException(404, f"案例不存在: {case}")
        if out:
            sub = str(out).replace("\\", "/").strip("/")
            if sub not in ("out", "out_offline") and not (
                    sub.startswith("history/") and sub.count("/") == 1
                    and ".." not in sub):
                raise HTTPException(400, "非法产物路径")
            candidates = [base / sub]
        else:
            # 与 _find_out_dir 一致：优先 out，再 out_offline
            candidates = [base / "out", base / "out_offline"]
        for out_dir in candidates:
            path = out_dir / "progress.json"
            if path.is_file():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    return {"step": "unknown", "steps": [], "elapsed_s": 0}
        # 无 progress：有报告则视为已完成
        for out_dir in candidates:
            if (out_dir / "report.json").is_file():
                return {"step": "done", "steps": [], "elapsed_s": 0}
        return {"step": "unknown", "steps": [], "elapsed_s": 0}

    @app.get("/api/case/diff")
    def case_diff(case: str, against: str = "out_offline") -> dict:
        """两份产物结论对照（增量重跑后的 diff）。against 为同案例子目录名。"""
        from app.core.dossier_diff import diff_conclusions

        current = _find_out_dir(cases_root, case)
        other = _safe_out_dir(cases_root, case, against)
        old = Dossier.from_json(other / "report.json")
        new = Dossier.from_json(current / "report.json")
        return {"case": case, "current": current.name, "against": against,
                **diff_conclusions(old, new)}

    @app.get("/api/reasoning_graph")
    def get_reasoning_graph(case: str,
                            clearance: str = "confidential",
                            out: str | None = None) -> dict:
        """推理轨迹图（与 dossier 同一权限口径：先 redact 再建图——
        涉密结论在图中显示为红章占位节点，绝不泄露原文）。"""
        from app.core.view_filter import redact_dossier

        out_dir = _safe_out_dir(cases_root, case, out)
        dossier, _ = _load_pair(out_dir)
        view, _stats = redact_dossier(dossier, clearance)
        return build_reasoning_graph(view)

    @app.post("/api/conclusion/edit")
    def edit_conclusion_api(req: ConclusionEditReq) -> dict:
        def apply(d: Dossier) -> dict:
            before = audit_all(d)
            try:
                edit_conclusion(d, req.conclusion_id, req.statement)
            except KeyError as exc:
                raise HTTPException(404, str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            after = audit_all(d)
            # 本次人工修改新引入的机械核对警示（黄/红）——人是最高权限，
            # 修改照常落卷，但「引入了未溯源内容」必须当场亮灯并入链
            keys_before = {(f["kind"], f.get("conclusion_id"), f["value"])
                           for f in before}
            introduced = [f for f in after
                          if (f["kind"], f.get("conclusion_id"), f["value"])
                          not in keys_before]
            for f in introduced:
                f["human_edit"] = True
            return {"n_new_flags": len(introduced), "flags": introduced}

        return _mutate(cases_root, req.case, "conclusion_edit",
                       {"conclusion_id": req.conclusion_id,
                        "statement": req.statement}, apply)

    @app.post("/api/conflict/override")
    def override_conflict_api(req: ConflictOverrideReq) -> dict:
        def apply(d: Dossier) -> None:
            try:
                override_resolution(d, req.conflict_id, req.winner_id)
            except KeyError as exc:
                raise HTTPException(404, str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc

        return _mutate(cases_root, req.case, "conflict_override",
                       {"conflict_id": req.conflict_id,
                        "winner_id": req.winner_id}, apply)

    @app.post("/api/case/reset")
    def reset_case(req: CaseResetReq) -> dict:
        """撤销本案例全部人工修改：还原到首次修改前的快照。

        重置本身也是人工动作——在还原后的链上追加 case_reset 事件，
        「可还原」不等于「无痕」。无快照（从未人工修改过）时 422。"""
        out_dir = _find_out_dir(cases_root, req.case)
        pristine_report = out_dir / _PRISTINE_REPORT
        if not pristine_report.is_file():
            raise HTTPException(422, "无快照可还原（本案例尚无人工修改）")
        dossier = Dossier.from_json(pristine_report)
        chain = (HashChain.from_jsonl(out_dir / _PRISTINE_CHAIN)
                 if (out_dir / _PRISTINE_CHAIN).is_file() else HashChain())
        chain.append("case_reset", "human", {"restored_to": "pristine"})
        dossier.to_json(out_dir / "report.json")
        chain.to_jsonl(out_dir / "chain.jsonl")
        return _dossier_payload(out_dir)

    @app.post("/api/evidence/weight")
    def set_weight(req: EvidenceWeightReq) -> dict:
        if not 0.0 <= req.weight <= 2.0:
            raise HTTPException(422, "weight 须在 [0, 2]")

        def apply(d: Dossier) -> None:
            ev = d.evidence(req.evidence_id)
            if ev is None:
                raise HTTPException(404, f"证据不存在: {req.evidence_id}")
            ev.weight = round(req.weight, 2)

        return _mutate(cases_root, req.case, "evidence_weight",
                       {"evidence_id": req.evidence_id, "weight": req.weight}, apply)

    @app.post("/api/evidence/remove")
    def remove_evidence(req: EvidenceRemoveReq) -> dict:
        def apply(d: Dossier) -> None:
            if d.evidence(req.evidence_id) is None:
                raise HTTPException(404, f"证据不存在: {req.evidence_id}")
            d.remove_evidence(req.evidence_id)

        return _mutate(cases_root, req.case, "evidence_removed",
                       {"evidence_id": req.evidence_id}, apply)

    @app.post("/api/evidence/relation")
    def set_relation(req: EvidenceRelationReq) -> dict:
        """改证据关系标注（相关/因果/专家判断）→ 重算置信度 + 因果闸。

        现场演示：把无机制词的证据改成「因果」会亮黄牌并压掉加成。
        """
        from app.core.evidence import RelationKind

        try:
            kind = RelationKind(req.relation)
        except ValueError as exc:
            raise HTTPException(
                422, "relation 须为 causation/correlation/expert_judgment"
            ) from exc

        def apply(d: Dossier) -> None:
            ev = d.evidence(req.evidence_id)
            if ev is None:
                raise HTTPException(404, f"证据不存在: {req.evidence_id}")
            ev.relation = kind

        return _mutate(cases_root, req.case, "evidence_relation",
                       {"evidence_id": req.evidence_id,
                        "relation": kind.value}, apply)

    @app.post("/api/source/relevance")
    def set_relevance(req: RelevanceOverrideReq) -> dict:
        """相关性人工裁决：机械分层可能错杀同义表述——人是最高权限，
        强制纳入/排除即时生效并入链（relevance_override 持久化，
        classify_sources 尊重之）。"""
        if req.override not in ("include", "exclude", ""):
            raise HTTPException(422, "override 须为 include/exclude/空串")

        def apply(d: Dossier) -> None:
            for src in d.sources:
                if src.id == req.source_id:
                    src.relevance_override = req.override
                    return
            raise HTTPException(404, f"信源不存在: {req.source_id}")

        return _mutate(cases_root, req.case, "source_relevance",
                       {"source_id": req.source_id,
                        "override": req.override or "auto"}, apply)

    @app.post("/api/source/credibility")
    def set_credibility(req: CredibilityReq) -> dict:
        if not 0.0 <= req.credibility <= 1.0:
            raise HTTPException(422, "credibility 须在 [0, 1]")

        def apply(d: Dossier) -> None:
            for src in d.sources:
                if src.id == req.source_id:
                    src.credibility = round(req.credibility, 2)
                    return
            raise HTTPException(404, f"信源不存在: {req.source_id}")

        return _mutate(cases_root, req.case, "source_credibility",
                       {"source_id": req.source_id,
                        "credibility": req.credibility}, apply)

    @app.post("/api/chain/verify")
    def verify_chain(req: dict) -> dict:
        out_dir = _find_out_dir(cases_root, str(req.get("case") or ""))
        _, chain = _load_pair(out_dir)
        result = chain.verify_chain()
        return {"ok": result.ok, "bad_index": result.bad_index,
                "reason": result.reason, "n_records": len(chain.records),
                "signed": result.signed}

    @app.post("/api/chain/tamper_demo")
    def tamper_demo(req: dict) -> dict:
        """篡改演示：在内存副本里改掉一条记录的 payload（文件不动），
        校验立即变红——「改一字即红」的现场演示口。"""
        out_dir = _find_out_dir(cases_root, str(req.get("case") or ""))
        _, chain = _load_pair(out_dir)
        if len(chain.records) < 2:
            raise HTTPException(422, "链太短，无法演示篡改")
        honest = chain.verify_chain()
        tampered = HashChain(copy.deepcopy(chain.records), key=chain.key)
        target = tampered.records[1]
        target.payload["__tampered__"] = "此处被人为修改"
        red = tampered.verify_chain()
        return {
            "honest_ok": honest.ok,
            "tampered_ok": red.ok,
            "bad_index": red.bad_index,
            "reason": red.reason,
            "tampered_record_event": target.event,
        }

    @app.get("/api/export_audit")
    def export_audit(case: str = "", out: str = "",
                     clearance: str = "confidential"):
        """导出可移交的研判审计包（zip：报告 + 链 + 核验摘要）。

        out 可指定 out / out_offline / history/<id>；缺省取最新产物。
        clearance=public/internal 时导出脱敏报告且不含 chain.jsonl
        （链是全量真相，不得借导出绕过视图）。
        """
        from fastapi.responses import Response

        from app.core.audit_pack import build_audit_pack

        case = str(case or "").strip()
        if not case:
            raise HTTPException(422, "缺少 case")
        out_dir = _safe_out_dir(cases_root, case, out or None)
        data = build_audit_pack(out_dir, case=case, clearance=clearance)
        from app.core.view_filter import normalize_clearance
        level = normalize_clearance(clearance)
        suffix = "-redacted" if level != "confidential" else ""
        fname = f"veritas-audit-{case}{suffix}.zip"
        return Response(
            content=data,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{fname}"',
                "Cache-Control": "no-store",
            },
        )

    @app.post("/api/demo/external_reject")
    def demo_external_reject() -> dict:
        """答辩演示：外部智能体假引文入卷 → 打回并署名（不改磁盘案卷）。"""
        from app.demo_external import run_external_reject_demo

        return run_external_reject_demo()

    return app


def main() -> int:
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="veritas 可视化工作台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--insecure-lan", action="store_true",
        help="允许绑定非本机地址（工作台无鉴权；局域网暴露有风险）")
    args = parser.parse_args()

    host = (args.host or "127.0.0.1").strip()
    loopback = {"127.0.0.1", "localhost", "::1"}
    if host not in loopback and not args.insecure_lan:
        print(
            f"拒绝绑定 {host}：工作台接口无鉴权，默认只允本机。"
            f"确需局域网访问请加 --insecure-lan（示例："
            f"python -m app.server --host 0.0.0.0 --insecure-lan）。",
            file=sys.stderr,
        )
        return 2
    if host not in loopback and args.insecure_lan:
        print(
            f"⚠ 已启用 --insecure-lan：监听 {host}，任意能连上的主机"
            f"可改案卷/触发研判/写入模型密钥。仅限受控演示网。",
            file=sys.stderr,
        )

    from app.core.hashchain import ensure_demo_chain_key

    ensure_demo_chain_key()

    import uvicorn

    print(f"veritas 工作台: http://{args.host}:{args.port}/")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
