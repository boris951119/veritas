"""审计包：可移交 zip，含报告/链/核验摘要。"""

import json
import zipfile
from io import BytesIO
from pathlib import Path

from app.core.audit_pack import build_audit_pack
from app.core.evidence import Dossier
from app.core.hashchain import HashChain


def _seed_out(tmp_path: Path, *, key: bytes | None = None) -> Path:
    out = tmp_path / "out"
    out.mkdir()
    Dossier(question="审计包测试议题").to_json(out / "report.json")
    (out / "report.md").write_text("# demo\n", encoding="utf-8")
    chain = HashChain(key=key)
    chain.append("case_loaded", "pipeline", {"case": "demo"}, ts="t1")
    chain.append("done", "pipeline", {}, ts="t2")
    chain.to_jsonl(out / "chain.jsonl")
    return out


def test_build_audit_pack_contents(tmp_path, monkeypatch):
    monkeypatch.delenv("VERITAS_CHAIN_KEY", raising=False)
    out = _seed_out(tmp_path, key=None)
    data = build_audit_pack(out, case="demo")
    with zipfile.ZipFile(BytesIO(data)) as zf:
        names = set(zf.namelist())
        assert "report.json" in names
        assert "report.md" in names
        assert "chain.jsonl" in names
        assert "manifest.json" in names
        assert "VERIFY.json" in names
        assert "README.txt" in names
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["case"] == "demo"
    assert manifest["chain"]["ok"] is True
    assert manifest["chain"]["signing"] == "hash-only"


def test_build_audit_pack_signed(tmp_path, monkeypatch):
    monkeypatch.setenv("VERITAS_CHAIN_KEY", "pack-key")
    out = _seed_out(tmp_path, key=b"pack-key")
    data = build_audit_pack(out, case="demo")
    with zipfile.ZipFile(BytesIO(data)) as zf:
        verify = json.loads(zf.read("VERIFY.json"))
    assert verify["ok"] is True
    assert verify["signed"] is True
    assert verify["signing"] == "hmac-sha256"


def test_low_clearance_audit_pack_omits_chain_and_secrets(tmp_path, monkeypatch):
    from app.core.evidence import (
        Conclusion, EvidenceNode, Segment, Source, SourceType,
    )

    monkeypatch.delenv("VERITAS_CHAIN_KEY", raising=False)
    out = tmp_path / "out"
    out.mkdir()
    d = Dossier(question="客户B回款？")
    pub = Source.create("公开", SourceType.REPORT, id="SRC1",
                        classification="public")
    pub.segments.append(Segment(id="SRC1#s1", source_id="SRC1",
                                text="回款512万元。"))
    sec = Source.create("涉密", SourceType.REPORT, id="SRC2",
                        classification="confidential")
    sec.segments.append(Segment(id="SRC2#s1", source_id="SRC2",
                                text="涉外款项800万元。"))
    d.add_source(pub)
    d.add_source(sec)
    d.conclusions.append(Conclusion.create("回款512万元", author="a", id="CON1"))
    d.add_evidence(EvidenceNode.create("CON1", "回款512万元", ["SRC1#s1"]))
    d.conclusions.append(Conclusion.create("涉外款项800万元", author="a", id="CON2"))
    d.add_evidence(EvidenceNode.create("CON2", "涉外款项800万元", ["SRC2#s1"]))
    d.to_json(out / "report.json")
    (out / "report.md").write_text("涉密 800万元\n", encoding="utf-8")
    chain = HashChain()
    chain.append("case_loaded", "pipeline", {"secret": "800万元"}, ts="t1")
    chain.to_jsonl(out / "chain.jsonl")

    data = build_audit_pack(out, case="demo", clearance="public")
    with zipfile.ZipFile(BytesIO(data)) as zf:
        names = set(zf.namelist())
        assert "chain.jsonl" not in names
        assert "report.json" in names
        report = json.loads(zf.read("report.json"))
        blob = json.dumps(report, ensure_ascii=False)
        assert "800万元" not in blob
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["redacted"] is True
    assert manifest["chain"]["included"] is False
    assert "512万元" in blob
