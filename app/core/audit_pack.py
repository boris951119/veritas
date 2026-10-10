"""研判审计包：可移交的信任物（导出给客户/审计独立核验）。

概念来自「信任可带走」：不只本机绿灯，而是一份 zip——含报告、
哈希链、核验摘要与签名状态——别人拿去也能验。

密级：clearance=confidential（默认）导出全量报告+链；
public/internal 只导出脱敏报告，并**不附 chain.jsonl**——链上是
全量真相，低权限不得借审计包绕过视图过滤。
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.core.evidence import Dossier
from app.core.hashchain import HashChain, chain_key_from_env
from app.core.view_filter import normalize_clearance, redact_dossier


def build_audit_pack(out_dir: Path, case: str = "",
                     clearance: str | None = "confidential") -> bytes:
    """把 out_dir 打成审计 zip（内存字节）。缺文件则跳过，不抛。"""
    out_dir = Path(out_dir)
    level = normalize_clearance(clearance)
    full = level == "confidential"

    chain_path = out_dir / "chain.jsonl"
    chain = HashChain.from_jsonl(chain_path) if chain_path.is_file() else HashChain()
    key = chain_key_from_env()
    verify = chain.verify_chain(key=key)
    signed = bool(key) and bool(chain.records) and all(r.mac for r in chain.records)

    report_path = out_dir / "report.json"
    redacted_stats: dict = {}
    view_dict: dict | None = None
    if report_path.is_file() and not full:
        dossier = Dossier.from_json(report_path)
        view, redacted_stats = redact_dossier(dossier, level)
        view_dict = view.to_dict()

    manifest = {
        "case": case or out_dir.parent.name,
        "out_dir": out_dir.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "clearance": level,
        "redacted": not full,
        "redaction": redacted_stats or None,
        "chain": {
            "n_records": len(chain.records),
            "ok": verify.ok,
            "bad_index": verify.bad_index,
            "reason": verify.reason,
            "signed": signed,
            "signing": "hmac-sha256" if key else "hash-only",
            "included": full,
        },
        "files": [],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if full:
            for name in ("report.json", "report.md", "chain.jsonl"):
                path = out_dir / name
                if path.is_file():
                    zf.write(path, name)
                    manifest["files"].append(name)
        else:
            if view_dict is not None:
                zf.writestr(
                    "report.json",
                    json.dumps(view_dict, ensure_ascii=False, indent=2) + "\n",
                )
                manifest["files"].append("report.json")
            md_path = out_dir / "report.md"
            if md_path.is_file():
                # 低密级：不附原文 md（可能含涉密数字），改写提示页
                zf.writestr(
                    "report.md",
                    f"# 脱敏报告视图（clearance={level}）\n\n"
                    f"完整 Markdown 未导出。请阅读同包 `report.json` "
                    f"（已按密级过滤）。\n",
                )
                manifest["files"].append("report.md")
            # 故意不附 chain.jsonl

        zf.writestr(
            "VERIFY.json",
            json.dumps(manifest["chain"], ensure_ascii=False, indent=2) + "\n",
        )
        zf.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )
        tip = (
            "veritas 研判审计包\n"
            f"案例：{manifest['case']}\n"
            f"密级视图：{level}"
            f"{'（全量）' if full else '（脱敏；不含 chain.jsonl）'}\n"
            f"链核验：{'通过' if verify.ok else '失败 — ' + verify.reason}\n"
            f"签名：{'HMAC-SHA256（已签）' if signed else ('未配置密钥（仅哈希自洽）' if not key else '密钥已配置但存在未签名记录')}\n"
            "独立核验：用同一密钥对 chain.jsonl 调用 HashChain.verify_chain。\n"
            "看 signed，不只看 ok：缺 mac 的旧记录哈希可过，但 signed 为 false。\n"
            "演示密钥 veritas-contest-demo-hmac 是公开值，只供现场核验，不是生产密钥。\n"
        )
        if not full:
            tip += (
                "低密级包不含哈希链原文——链记录全量真相，防止借审计导出绕过权限视图。\n"
            )
        zf.writestr("README.txt", tip)
    return buf.getvalue()
