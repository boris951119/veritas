"""外部假引文入卷演示：假的打回、真的留下、署名可指认。"""

from app.demo_external import run_external_reject_demo


def test_demo_external_ingest_rejects_fake_keeps_true():
    r = run_external_reject_demo()
    attr = r["attribution"]
    assert attr["n_rejected"] >= 1
    assert attr["agent"] == "灵境-研判助手"
    assert attr["agent_id"] == "lingjing-judge-demo"
    assert r["true_quote_kept"] is True
    assert r["fake_quote_surviving"] is False
