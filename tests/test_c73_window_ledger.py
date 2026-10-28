"""C-73 窗口账：call_log 四键＋accounting 聚合＋报告一行；判定／预算零改。"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

from app.agents.base import Analyst
from app.config import Settings
from app.core.evidence import Dossier, Segment, Source, SourceType
from app.core.hashchain import HashChain
from app.core.prompt_guard import (
    build_window_ledger,
    format_window_ledger_line,
)
from app.llm.model_client import ModelClient
from app.pipeline import RunDeps, RunSpec, _render_window_ledger, render_report_md, run_case

_ROOT = Path(__file__).resolve().parents[1]

# 与 tests/test_agents_pipeline 同形：桩跑通 run_case 的最小合法 JSON
_RUN_CASE_JSON = """```json
{"conclusions": [
  {"statement": "固态电池能量密度占优",
   "evidence": [{"quote": "能量密度显著高于液态锂离子电池",
                 "segment_id": "SRC1#s1",
                 "relation": "correlation", "level": "A", "note": "直接引证"}]}
]}
```"""


def _resp(content="ok", prompt=10, completion=5, usage=True):
    body = {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
    }
    if usage is True:
        body["usage"] = {"prompt_tokens": prompt, "completion_tokens": completion}
    elif usage is False:
        pass
    elif usage is None:
        body["usage"] = {"prompt_tokens": None, "completion_tokens": completion}
    else:
        body["usage"] = usage
    return body


def _settings(**kw) -> Settings:
    kw.setdefault("models", ["test-model"])
    kw.setdefault("model_context_tokens", 16384)
    kw.setdefault("zh_chars_per_token", 1.45)
    return Settings(
        models=kw.pop("models"),
        llm_max_retries=1,
        retry_backoff_base=0.0,
        **kw,
    )


def _load_mutated(name: str, old: str, new: str, tmp_path: Path,
                  *, replace_all: bool = False):
    raw = (_ROOT / name).read_text(encoding="utf-8")
    assert old in raw, f"变异针漂移：{name!r}"
    dest = tmp_path / name.replace("/", "__")
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = raw.replace(old, new) if replace_all else raw.replace(old, new, 1)
    dest.write_text(text, encoding="utf-8")
    mod_name = f"c73_mut_{dest.stem}_{abs(hash(new)) & 0xFFFF:x}"
    spec = importlib.util.spec_from_file_location(mod_name, dest)
    mod = types.ModuleType(mod_name)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_mini_case(tmp_path: Path) -> Path:
    case = tmp_path / "case"
    case.mkdir()
    (case / "manifest.yaml").write_text(
        "question: 固态电池 2030 能否规模上车？\n"
        "sources:\n  - file: a.md\n    type: paper\n",
        encoding="utf-8",
    )
    (case / "a.md").write_text(
        "# 摘要\n\n本次测评显示固态电池的能量密度显著高于液态锂离子电池，"
        "但成本仍高于预期。\n",
        encoding="utf-8",
    )
    return case


def _run_case_with_model_client(case_dir: Path, out_dir: Path,
                                client: ModelClient):
    single = [Analyst("mainstream", "测试角色", client, "test-model")]
    return run_case(RunSpec(case_dir=case_dir, out_dir=out_dir),
                    RunDeps(client=client, analysts=single))


# ---- 件①／④：桩 usage 1234 逐字进账；None 不许回填 ----
def test_c73_server_prompt_tokens_verbatim_1234():
    def completion(**kw):
        return _resp("hi", prompt=1234)

    client = ModelClient(_settings(), completion_fn=completion)
    msgs = [
        {"role": "system", "content": "你是分析师甲"},
        {"role": "user", "content": "议题"},
    ]
    client.chat("test-model", msgs)
    entry = client.call_log[-1]
    assert entry["server_prompt_tokens"] == 1234
    assert entry["server_reported"] is True
    assert entry["prompt_chars"] == sum(len(m["content"]) for m in msgs)
    assert "est_tokens" in entry and isinstance(entry["est_tokens"], int)
    assert "over_window" in entry
    # 1234 << 16384
    assert entry["over_window"] is False


def test_c73_missing_usage_no_est_backfill():
    def completion(**kw):
        return _resp("hi", usage=False)

    client = ModelClient(_settings(), completion_fn=completion)
    client.chat("test-model", [{"role": "user", "content": "x" * 100}])
    entry = client.call_log[-1]
    assert entry["server_prompt_tokens"] is None
    assert entry["server_reported"] is False
    assert entry["est_tokens"] > 0  # 本地估有数
    # 硬禁：不得用 est 冒充真报
    assert entry["server_prompt_tokens"] != entry["est_tokens"]
    assert entry["over_window"] is None  # 无真数 ⇒ 不许判超窗


def test_c73_null_prompt_tokens_no_backfill():
    def completion(**kw):
        return _resp("hi", usage=None)

    client = ModelClient(_settings(), completion_fn=completion)
    client.chat("test-model", [{"role": "user", "content": "hello"}])
    entry = client.call_log[-1]
    assert entry["server_prompt_tokens"] is None
    assert entry["server_reported"] is False


def test_c73_over_window_true_when_server_exceeds():
    def completion(**kw):
        return _resp("hi", prompt=20000)

    client = ModelClient(
        _settings(model_context_tokens=16384), completion_fn=completion)
    client.chat("test-model", [{"role": "user", "content": "q"}])
    assert client.call_log[-1]["over_window"] is True


def test_c73_window_unchecked_over_window_none():
    def completion(**kw):
        return _resp("hi", prompt=100)

    client = ModelClient(
        _settings(model_context_tokens=0), completion_fn=completion)
    client.chat("test-model", [{"role": "user", "content": "q"}])
    assert client.call_log[-1]["window_tokens"] is None
    assert client.call_log[-1]["over_window"] is None


def test_c73_unchecked_est_tokens_not_fake_zero():
    """R-C73-1 件③：model_context_tokens=0 ⇒ est_tokens=None（没估），不是假零 0。"""
    def completion(**kw):
        return _resp("hi", prompt=800)

    client = ModelClient(
        _settings(model_context_tokens=0, zh_chars_per_token=1.45),
        completion_fn=completion,
    )
    client.chat("test-model", [{"role": "user", "content": "y" * 1450}])
    entry = client.call_log[-1]
    assert entry["prompt_chars"] == 1450
    assert entry["window_tokens"] is None
    assert entry["over_window"] is None
    assert entry["est_tokens"] is None
    assert entry["est_tokens"] != 0


# ---- 聚合 ----
def test_c73_build_window_ledger_aggregates():
    log = [
        {
            "model": "m", "system_hint": "分析师甲角色",
            "prompt_chars": 1450, "est_tokens": 1000,
            "server_prompt_tokens": 1000, "server_reported": True,
            "over_window": False, "window_tokens": 16384,
        },
        {
            "model": "m", "system_hint": "主席汇总",
            "prompt_chars": 2900, "est_tokens": 2000,
            "server_prompt_tokens": 1800, "server_reported": True,
            "over_window": False, "window_tokens": 16384,
        },
        {
            "model": "m", "system_hint": "归并",
            "prompt_chars": 100, "est_tokens": 70,
            "server_prompt_tokens": None, "server_reported": False,
            "over_window": None, "window_tokens": 16384,
        },
        # embedding 形——无 server_reported ⇒ 跳过
        {"model": "m", "kind": "embedding", "input_tokens": 5},
    ]
    led = build_window_ledger(log, window_tokens=16384)
    assert led["n_calls"] == 3
    assert led["n_server_reported"] == 2
    assert led["max_server_prompt_tokens"] == 1800
    assert led["window_tokens"] == 16384
    assert led["n_over_window"] == 0
    assert led["min_true_chars_per_token"] == pytest.approx(1.45, rel=1e-6)
    assert len(led["rows"]) == 3
    legs = {r["leg"] for r in led["rows"]}
    assert any("分析师" in x for x in legs)
    assert any("主席" in x for x in legs)
    assert any("归并" in x for x in legs)


def test_c73_three_legs_visible_in_rows():
    """判据 c：分析师／归并／主席三条腿各一行（合成夹具）。"""
    hints = ["你是分析师甲。", "请归并三方结论。", "你是主席，请汇总。"]
    log = []
    for i, h in enumerate(hints):
        log.append({
            "model": "m", "system_hint": h,
            "prompt_chars": 100 + i, "est_tokens": 70 + i,
            "server_prompt_tokens": 80 + i, "server_reported": True,
            "over_window": False, "window_tokens": 16384,
        })
    led = build_window_ledger(log, window_tokens=16384)
    assert led["n_calls"] == 3
    joined = " ".join(r["leg"] for r in led["rows"])
    assert "分析师" in joined and "归并" in joined and "主席" in joined


# ---- 报告面 ----
def test_c73_report_line_present_when_no_server():
    d = Dossier(question="Q")
    d.accounting["window_ledger"] = build_window_ledger([], window_tokens=16384)
    lines: list[str] = []
    _render_window_ledger(lines, d)
    text = "\n".join(lines)
    assert "窗口账（服务端真报）" in text
    assert "服务端未报，未据此判定" in text
    assert "漏检率" not in text and "召回率" not in text


def test_c73_report_line_with_server_numbers():
    led = build_window_ledger([{
        "model": "m", "system_hint": "分析师",
        "prompt_chars": 1450, "est_tokens": 1000,
        "server_prompt_tokens": 1000, "server_reported": True,
        "over_window": False, "window_tokens": 16384,
    }], window_tokens=16384)
    line = format_window_ledger_line(led)
    assert "最长提示词 1000" in line
    assert "窗口 16384" in line
    assert "未据此判定" not in line
    assert "漏检率" not in line


def test_c73_offline_rerender_old_report_still_shows_line(tmp_path):
    """判据 g：旧产物无 window_ledger 时离线重渲仍有那一行＋未据此判定。"""
    d = Dossier(question="议题")
    src = Source.create("S1", SourceType.REPORT, id="S1")
    src.segments.append(Segment(id="S1#s1", source_id="S1", text="正文。", index=0))
    d.add_source(src)
    # 故意不写 window_ledger
    md = render_report_md(d, HashChain(), [])
    assert "窗口账（服务端真报）" in md
    assert "服务端未报，未据此判定" in md


# ---- 反向刀 ----
def test_c73_knife_drop_key_must_red(tmp_path):
    """摘四键之一（server_prompt_tokens）⇒ 正向格红。"""
    old = '"server_prompt_tokens": server_prompt_tokens,'
    new = '# c73-knife drop\n            # "server_prompt_tokens": server_prompt_tokens,'
    mod = _load_mutated("app/llm/model_client.py", old, new, tmp_path)

    def completion(**kw):
        return {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1234, "completion_tokens": 1},
        }

    # 用变异模块的 ModelClient
    client = mod.ModelClient(
        Settings(models=["test-model"], llm_max_retries=1,
                 retry_backoff_base=0.0, model_context_tokens=16384),
        completion_fn=completion,
    )
    client.chat("test-model", [{"role": "user", "content": "hi"}])
    entry = client.call_log[-1]
    assert "server_prompt_tokens" not in entry


def test_c73_knife_over_window_always_false_must_red(tmp_path):
    """over_window 恒 False ⇒ 超窗夹具读成 False（本格断言变异生效）。"""
    old = "            over_window = bool(server_prompt_tokens > window_tokens)"
    new = "            over_window = False  # c73-knife"
    mod = _load_mutated("app/llm/model_client.py", old, new, tmp_path)

    def completion(**kw):
        return {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 99999, "completion_tokens": 1},
        }

    client = mod.ModelClient(
        Settings(models=["test-model"], llm_max_retries=1,
                 retry_backoff_base=0.0, model_context_tokens=100),
        completion_fn=completion,
    )
    client.chat("test-model", [{"role": "user", "content": "hi"}])
    assert client.call_log[-1]["over_window"] is False  # 变异后恒假
    # 真树应为 True——对照
    real = ModelClient(
        _settings(model_context_tokens=100), completion_fn=completion)
    real.chat("test-model", [{"role": "user", "content": "hi"}])
    assert real.call_log[-1]["over_window"] is True


def test_c73_window_ledger_survives_kept_via_run_case(tmp_path):
    """R-C73-1 件① 正向：桩 client 走 run_case ⇒ report.json 账里 window_ledger 在场且 rows 非空。"""
    case = _make_mini_case(tmp_path)
    out = tmp_path / "out"

    def completion(**kw):
        return {
            "choices": [{"message": {"content": _RUN_CASE_JSON},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30},
        }

    client = ModelClient(_settings(), completion_fn=completion)
    _run_case_with_model_client(case, out, client)
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    wl = (report.get("accounting") or {}).get("window_ledger")
    assert isinstance(wl, dict), report.get("accounting")
    assert wl.get("rows"), wl


def test_c73_knife_kept_drops_window_ledger_must_red(tmp_path):
    """R-C73-1 件① 反向：tmp 副本两处 kept 删 window_ledger ⇒ 落盘账里该键消失。"""
    # 两处 kept 元组都以 "window_ledger")} 收尾（早退独占一行／主路径跟 claim_slots）
    needle = '"window_ledger")}'
    raw = (_ROOT / "app/pipeline.py").read_text(encoding="utf-8")
    assert raw.count(needle) >= 2, "变异针漂移：两处 kept 应各含 window_ledger"
    mod = _load_mutated(
        "app/pipeline.py", needle, ")}", tmp_path, replace_all=True)

    case = _make_mini_case(tmp_path)
    out = tmp_path / "out_mut"

    def completion(**kw):
        return {
            "choices": [{"message": {"content": _RUN_CASE_JSON},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30},
        }

    client = ModelClient(_settings(), completion_fn=completion)
    single = [Analyst("mainstream", "测试角色", client, "test-model")]
    mod.run_case(RunSpec(case_dir=case, out_dir=out),
                 RunDeps(client=client, analysts=single))
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    acc = report.get("accounting") or {}
    assert "window_ledger" not in acc, acc.keys()


def test_c73_min_true_chars_per_token_uses_server_not_est():
    """R-C73-1 件②：密度只许 chars/server，不许 chars/est 自比。"""
    def completion(**kw):
        return _resp("ok", prompt=800)

    client = ModelClient(
        _settings(zh_chars_per_token=1.45, model_context_tokens=16384),
        completion_fn=completion,
    )
    client.chat("test-model", [{"role": "user", "content": "x" * 1450}])
    entry = client.call_log[-1]
    assert entry["prompt_chars"] == 1450
    assert entry["server_prompt_tokens"] == 800
    assert entry["est_tokens"] == int(1450 / 1.45)  # ≈1000
    led = build_window_ledger(client.call_log, window_tokens=16384)
    assert led["min_true_chars_per_token"] == pytest.approx(1450 / 800)
    assert led["min_true_chars_per_token"] != pytest.approx(1450 / 1000)


def test_c73_knife_est_backfill_server_must_differ_from_contract(tmp_path):
    """把 server 改成用 est 回填 ⇒ 与「缺 usage⇒None」契约冲突（本格红名位）。"""
    old = (
        "        server_prompt_tokens = _get_server_prompt_tokens(response)\n"
        "        server_reported = server_prompt_tokens is not None"
    )
    new = (
        "        server_prompt_tokens = _get_server_prompt_tokens(response)\n"
        "        if server_prompt_tokens is None:\n"
        "            server_prompt_tokens = est_tokens  # c73-knife 自比回填\n"
        "        server_reported = True"
    )
    mod = _load_mutated("app/llm/model_client.py", old, new, tmp_path)

    def completion(**kw):
        return {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            # 无 usage
        }

    client = mod.ModelClient(
        Settings(models=["test-model"], llm_max_retries=1,
                 retry_backoff_base=0.0, model_context_tokens=16384,
                 zh_chars_per_token=1.45),
        completion_fn=completion,
    )
    client.chat("test-model", [{"role": "user", "content": "x" * 145}])
    entry = client.call_log[-1]
    # 变异后会把 est 填进 server —— 与契约相反；真树测试
    # test_c73_missing_usage_no_est_backfill 会因此红
    assert entry["server_prompt_tokens"] == entry["est_tokens"]
    assert entry["server_reported"] is True


# ---- 〔181〕/〔182〕 记账的聚合口径（架构师自补的一小笔，C-74 前置）----
def test_c73_weighted_density_not_pulled_by_short_leg():
    """短提示词只许拉偏下界，不许拉偏加权口径（真产物指纹：1.24 vs 1.54）。"""
    log = [
        {"model": "m", "system_hint": "检索拓展",
         "prompt_chars": 487, "est_tokens": 336,
         "server_prompt_tokens": 391, "server_reported": True,
         "over_window": False, "window_tokens": 16384},
        {"model": "m", "system_hint": "你是分析师甲。",
         "prompt_chars": 21594, "est_tokens": 14892,
         "server_prompt_tokens": 14011, "server_reported": True,
         "over_window": False, "window_tokens": 16384},
    ]
    led = build_window_ledger(log, window_tokens=16384)
    assert led["min_true_chars_per_token"] == pytest.approx(487 / 391)
    assert led["true_chars_per_token_weighted"] == pytest.approx(
        (487 + 21594) / (391 + 14011))
    assert led["true_chars_per_token_max_leg"] == pytest.approx(21594 / 14011)
    # 反「拿下界当主口径」：两值必须真的不同（相同＝这格白写）
    assert abs(led["true_chars_per_token_weighted"]
               - led["min_true_chars_per_token"]) > 0.2


def test_c73_max_leg_density_ties_take_first():
    """并列最长取先出现＝不许吃集合序（我另一把尺在 10-② 上栽过的同族坑）。"""
    log = [
        {"model": "m", "system_hint": "甲", "prompt_chars": 1000,
         "est_tokens": 700, "server_prompt_tokens": 1000,
         "server_reported": True, "over_window": False, "window_tokens": 16384},
        {"model": "m", "system_hint": "乙", "prompt_chars": 2000,
         "est_tokens": 1400, "server_prompt_tokens": 1000,
         "server_reported": True, "over_window": False, "window_tokens": 16384},
    ]
    led = build_window_ledger(log, window_tokens=16384)
    assert led["true_chars_per_token_max_leg"] == pytest.approx(1.0)


def test_c73_report_line_bias_uses_weighted_not_min():
    """出口面数值格：那一行的百分比只许长在加权口径上（换回 min 必红）。"""
    led = {
        "n_calls": 2, "n_server_reported": 2, "max_server_prompt_tokens": 14011,
        "window_tokens": 16384, "n_over_window": 0,
        "min_true_chars_per_token": 487 / 391,          # 1.2456 → +16.4%
        "true_chars_per_token_weighted": (487 + 21594) / (391 + 14011),
        "true_chars_per_token_max_leg": 21594 / 14011,
    }
    line = format_window_ledger_line(led)
    want = (led["true_chars_per_token_weighted"] / 1.45 - 1.0) * 100.0
    wrong = (led["min_true_chars_per_token"] / 1.45 - 1.0) * 100.0
    assert f"估算比服务端高报 {want:+.1f}%" in line, line
    assert f"估算比服务端高报 {wrong:+.1f}%" not in line, line
    # 符号格：真密度 1.65 ＞ 常量 1.45 ⇒ 一定是「高报」、数必须为正
    assert want > 0, want
    assert "按字数加权" in line, line
