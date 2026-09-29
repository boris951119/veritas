"""工作台服务端到端测试：临时案例 + 真实 uvicorn 线程 + urllib 探活。

覆盖：案例列表、dossier 读取、改权重/删证据/改可信度（重算+入链）、
链校验、篡改演示（改一字即红）。零 key、零网络。
"""

import json
import threading
import time
import urllib.request
from types import SimpleNamespace

import pytest

from app.agents.base import Analyst
from app.pipeline import run_case
from app.server import create_app

PANEL_JSON = """{"conclusions": [
  {"statement": "固态电池2030年前规模量产存在较大不确定性",
   "evidence": [{"quote": "全固态电芯的中试良率尚不足百分之四十",
                 "segment_id": "SRC1#s1", "relation": "correlation",
                 "level": "B", "note": "良率瓶颈"}]},
  {"statement": "半固态电池能量密度优势已获装车验证",
   "evidence": [{"quote": "能量密度显著高于传统液态锂离子电池",
                 "segment_id": "SRC1#s1", "relation": "correlation",
                 "level": "A", "note": "装车实证"}]}
]}"""


class FakeClient:
    def chat(self, model, messages, json_mode=False):
        return SimpleNamespace(content=PANEL_JSON)


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    cases_root = tmp_path_factory.mktemp("cases")
    case_dir = cases_root / "demo"
    case_dir.mkdir()
    (case_dir / "manifest.yaml").write_text(
        "question: 固态电池 2030 能否规模上车？\n"
        "sources:\n  - file: a.md\n    type: paper\n", encoding="utf-8")
    (case_dir / "a.md").write_text(
        "# 摘要\n\n2025 年行业测评显示，半固态电池包的能量密度显著高于传统"
        "液态锂离子电池。产线良率是当前最大瓶颈，全固态电芯的中试良率尚不足"
        "百分之四十。\n", encoding="utf-8")
    single = [Analyst("mainstream", "测试角色", FakeClient(), "test-model")]
    run_case(case_dir, out_dir=case_dir / "out", client=FakeClient(),
             analysts=single)

    import uvicorn

    app = create_app(cases_root=cases_root)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def test_index_serves_workbench_html(api):
    with urllib.request.urlopen(api + "/", timeout=5) as r:
        html = r.read().decode("utf-8")
    assert "veritas" in html and "研判工作台" in html


def test_list_and_get_dossier(api):
    cases = _get(api + "/api/cases")["cases"]
    assert {"name": "demo", "out_dir": "out"} in cases
    data = _get(api + "/api/dossier?case=demo")
    d = data["dossier"]
    assert len(d["conclusions"]) == 2
    assert d["panel"] == ["mainstream"]
    assert d["rejected"] == []
    assert data["chain"]["ok"] is True


def test_weight_update_recomputes_and_chains(api):
    before = _get(api + "/api/dossier?case=demo")
    con_id, n_ev = before["dossier"]["conclusions"][0]["id"], None
    ev = before["dossier"]["evidences"][0]
    old_conf = before["dossier"]["conclusions"][0]["confidence"]
    after = _post(api + "/api/evidence/weight",
                  {"case": "demo", "evidence_id": ev["id"], "weight": 0.1})
    con = next(c for c in after["dossier"]["conclusions"]
               if c["id"] == before["dossier"]["conclusions"][0]["id"])
    assert con["confidence"] != old_conf          # 置信度被重算
    assert ev["weight"] == 0.1 or any(e["weight"] == 0.1
                                      for e in after["dossier"]["evidences"])
    assert after["chain"]["n_records"] == before["chain"]["n_records"] + 1
    assert after["chain"]["ok"] is True           # human 事件入链后链仍自洽
    assert _post(api + "/api/chain/verify", {"case": "demo"})["ok"] is True


def test_remove_evidence(api):
    before = _get(api + "/api/dossier?case=demo")
    ev_id = before["dossier"]["evidences"][0]["id"]
    after = _post(api + "/api/evidence/remove",
                  {"case": "demo", "evidence_id": ev_id})
    assert all(e["id"] != ev_id for e in after["dossier"]["evidences"])
    assert any(r["evidence_id"] == ev_id for r in
               # 删除不进 rejected：rejected 只记录引文打回；这里只验证链增长
               after["dossier"].get("rejected", [])) is False
    assert after["chain"]["ok"]


def test_credibility_update(api):
    after = _post(api + "/api/source/credibility",
                  {"case": "demo", "source_id": "SRC1", "credibility": 0.55})
    src = next(s for s in after["dossier"]["sources"] if s["id"] == "SRC1")
    assert src["credibility"] == 0.55
    assert after["chain"]["ok"]


def test_tamper_demo_turns_red_without_touching_disk(api):
    honest = _post(api + "/api/chain/verify", {"case": "demo"})
    red = _post(api + "/api/chain/tamper_demo", {"case": "demo"})
    assert honest["ok"] is True            # 磁盘链完好
    assert red["honest_ok"] is True and red["tampered_ok"] is False
    assert red["bad_index"] == 1
    after = _post(api + "/api/chain/verify", {"case": "demo"})
    assert after["ok"] is True             # 演示后磁盘链依然通过


def test_unknown_case_404(api):
    with pytest.raises(Exception):
        _get(api + "/api/dossier?case=nope")


def test_case_reset_restores_pristine_and_chains(api):
    """重置 = 还原首次修改前快照 + case_reset 入链（可还原，但非无痕）。"""
    before = _get(api + "/api/dossier?case=demo")
    ev = before["dossier"]["evidences"][0]
    _post(api + "/api/evidence/remove", {"case": "demo", "evidence_id": ev["id"]})
    assert all(e["id"] != ev["id"] for e in
               _get(api + "/api/dossier?case=demo")["dossier"]["evidences"])

    after = _post(api + "/api/case/reset", {"case": "demo"})
    assert any(e["id"] == ev["id"] for e in after["dossier"]["evidences"])
    assert after["chain"]["ok"]

    # 重置后再改权重再重置：回到快照原值，链始终自洽
    _post(api + "/api/evidence/weight",
          {"case": "demo", "evidence_id": ev["id"], "weight": 0.1})
    again = _post(api + "/api/case/reset", {"case": "demo"})
    assert next(e["weight"] for e in again["dossier"]["evidences"]
                if e["id"] == ev["id"]) == 1.0
    assert again["chain"]["ok"]
