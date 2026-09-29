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
import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.audit import audit_all, summarize
from app.core.confidence import recompute_all
from app.core.evidence import Dossier
from app.core.hashchain import HashChain
from app.core.human_ops import edit_conclusion, override_resolution
from app.core.reasoning_graph import build_reasoning_graph

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEB_DIR = _REPO_ROOT / "web"
# 首次人工修改前的原始产物快照（重置端点的还原点；随 out* 一起被
# 打包脚本排除，不进携带包）
_PRISTINE_REPORT = "report.pristine.json"
_PRISTINE_CHAIN = "chain.pristine.jsonl"


def _cases_root(cases_root: Path | None) -> Path:
    return cases_root or (_REPO_ROOT / "cases")


def _find_out_dir(cases_root: Path | None, case: str) -> Path:
    base = _cases_root(cases_root) / case
    if not base.is_dir():
        raise HTTPException(404, f"案例不存在: {case}")
    for sub in ("out", "out_offline"):
        p = base / sub
        if (p / "report.json").is_file():
            return p
    raise HTTPException(404, f"案例 {case} 无研判产物（先跑 pipeline 或 demo_offline）")


def _load_pair(out_dir: Path) -> tuple[Dossier, HashChain]:
    dossier = Dossier.from_json(out_dir / "report.json")
    chain_path = out_dir / "chain.jsonl"
    chain = (HashChain.from_jsonl(chain_path) if chain_path.is_file()
             else HashChain())
    return dossier, chain


def _dossier_payload(out_dir: Path) -> dict:
    dossier, chain = _load_pair(out_dir)
    verify = chain.verify_chain()
    # 机械核对警示为派生视图：每次加载即时重算——人工修改与文件篡改
    # 都逃不过下一次读取（「改数字即红」的工作台侧实现）
    flags = audit_all(dossier)
    return {
        "case": out_dir.parent.name,
        "out_dir": out_dir.name,
        "dossier": dossier.to_dict(),
        "audit": {"flags": flags, **summarize(flags)},
        "chain": {
            "n_records": len(chain.records),
            "ok": verify.ok,
            "bad_index": verify.bad_index,
            "reason": verify.reason,
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
    chain.append(event, "human", {**payload, **(extra or {})})
    dossier.to_json(out_dir / "report.json")
    chain.to_jsonl(out_dir / "chain.jsonl")
    result = _dossier_payload(out_dir)
    if extra:
        result["op"] = extra
    return result



class EvidenceWeightReq(BaseModel):
    case: str
    evidence_id: str
    weight: float


class EvidenceRemoveReq(BaseModel):
    case: str
    evidence_id: str


class CredibilityReq(BaseModel):
    case: str
    source_id: str
    credibility: float


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


def create_app(cases_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="veritas 工作台", docs_url=None, redoc_url=None)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_WEB_DIR / "index.html")

    @app.get("/api/cases")
    def list_cases() -> dict:
        cases = []
        for d in sorted(_cases_root(cases_root).iterdir()):
            if not d.is_dir():
                continue
            for sub in ("out", "out_offline"):
                if (d / sub / "report.json").is_file():
                    cases.append({"name": d.name, "out_dir": sub})
                    break
        return {"cases": cases}

    @app.get("/api/dossier")
    def get_dossier(case: str) -> dict:
        return _dossier_payload(_find_out_dir(cases_root, case))

    @app.get("/api/reasoning_graph")
    def get_reasoning_graph(case: str) -> dict:
        out_dir = _find_out_dir(cases_root, case)
        dossier, _ = _load_pair(out_dir)
        return build_reasoning_graph(dossier)

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
                "reason": result.reason, "n_records": len(chain.records)}

    @app.post("/api/chain/tamper_demo")
    def tamper_demo(req: dict) -> dict:
        """篡改演示：在内存副本里改掉一条记录的 payload（文件不动），
        校验立即变红——「改一字即红」的现场演示口。"""
        out_dir = _find_out_dir(cases_root, str(req.get("case") or ""))
        _, chain = _load_pair(out_dir)
        if len(chain.records) < 2:
            raise HTTPException(422, "链太短，无法演示篡改")
        honest = chain.verify_chain()
        tampered = HashChain(copy.deepcopy(chain.records))
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
    args = parser.parse_args()

    import uvicorn

    print(f"veritas 工作台: http://{args.host}:{args.port}/")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
