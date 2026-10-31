"""demo_offline 的 out_root 分支必须真有人走。"""

from scripts.demo_offline import main


def test_demo_offline_out_root_writes_reports(tmp_path):
    dest = tmp_path / "demo"
    assert main(dest) == 0
    for name in ("demo-solid-state", "bi-delivery-risk", "rumor-vs-official"):
        assert (dest / name / "report.json").is_file()
