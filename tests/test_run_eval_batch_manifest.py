"""评测批跑写 manifest：换行题干不得弄坏 YAML。"""

from pathlib import Path

import yaml

from app.llm.yaml_robust import load_yaml_robust
from scripts.run_eval_batch import _write_manifest


def test_write_manifest_preserves_multiline_question(tmp_path: Path):
    case = tmp_path / "南山铝业"
    case.mkdir()
    pdf = case / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    q = ("南山铝业2024年：公司通过全资子公司出资建设印尼宾坦工业园"
         "年产多少吨电解铝、\n多少吨炭素项目")
    _write_manifest(case, q, [pdf], [])
    raw = (case / "manifest.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    assert isinstance(data, dict)
    assert "宾坦" in data["question"]
    assert "炭素" in data["question"]
    # 容错加载器也必须读到完整题干（不得回退成目录名）
    robust = load_yaml_robust(case / "manifest.yaml")
    assert "宾坦" in str(robust.get("question") or "")
