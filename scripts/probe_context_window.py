"""C-9 探针：模型窗口超发时，提示词被服务端怎么切？（架构师用，需本机模型在线，不进 tests）

问题：装箱器按「字」算预算（`config.py:111 material_char_budget=80_000`），模型按「token」吃。
      两者之间没有校验——超发时服务端是报错，还是静默剪掉？剪头还是剪尾？

跑法（零云端花费，只用本机 Ollama）：
    PYTHONPATH=. .venv/bin/python scripts/probe_context_window.py
    CHARS=10000,30000 MODEL=openai/qwen3:14b PYTHONPATH=. .venv/bin/python scripts/probe_context_window.py

读法：三列代号对应提示词的**头／中／尾**三个位置。「丢」＝那段根本没到达模型。
      系统代号或议题代号先丢，就意味着模型在**没有纪律、没有议题**的状态下作答——属结论质量问题。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

MODEL = os.environ.get("MODEL", "openai/veritas-qwen3-14b")
BASE_URL = os.environ.get("OLLAMA_BASE", "http://127.0.0.1:11434/v1")
KEY = os.environ.get("OLLAMA_KEY", "ollama")
CHARS = [int(x) for x in os.environ.get("CHARS", "20000,80000").split(",")]
FILL = ("华东集团于本月涉及停工与欠薪事项，通报第12条，金额3785万元，"
        "影响240人，以官方口径为准。")


def show_num_ctx() -> None:
    """Ollama 专有：读服务端真正生效的 num_ctx（原生上限与配置值往往不同）。"""
    try:
        req = urllib.request.Request(
            BASE_URL.rsplit("/v1", 1)[0] + "/api/show",
            data=json.dumps({"model": MODEL.split("/", 1)[-1]}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode())
        info = {k: v for k, v in (d.get("model_info") or {}).items()
                if "context_length" in k}
        print(f"服务端：原生 {info or '?'} | 生效参数 {str(d.get('parameters'))[:120]}")
    except Exception as e:  # 非 Ollama 端点就没有这个接口，不影响主探针
        print(f"服务端：读不到 num_ctx（{type(e).__name__}），仅按提示词暗号判定")


def main() -> None:
    import litellm

    show_num_ctx()
    print(f"模型 {MODEL} @ {BASE_URL}；暗号放在 系统头／议题行／资料末 三处\n")
    for n in CHARS:
        tag = f"K{n // 1000}K"
        sysp = f"你是分析师。本提示词第一行代号 SYS_{tag}。规则：只依据资料作答，引用 segment_id。"
        body = FILL * (n // len(FILL))
        userp = (f"研判议题：华东集团的停工与欠薪风险有多大？（议题代号 TOPIC_{tag}）\n"
                 f"资料清单：\n{body}\n资料最后代号 END_{tag}。\n"
                 "请回答：系统代号、议题代号、资料最后代号各是什么？每行一个，只回代号本身。")
        t0 = time.perf_counter()
        try:
            r = litellm.completion(model=MODEL, api_base=BASE_URL, api_key=KEY,
                                   messages=[{"role": "system", "content": sysp},
                                             {"role": "user", "content": userp}],
                                   max_tokens=6000, temperature=0, drop_params=True)
        except (litellm.LiteLLMException, urllib.error.URLError) as e:
            print(f"{n:>7}字 → 调用失败（{time.perf_counter() - t0:.0f}s）：{str(e)[:160]}")
            continue
        out = (r.choices[0].message.content or "").replace("\n", " ")
        hit = lambda t: "中" if t in out else "丢"  # noqa: E731
        print(f"{n:>7}字 → 服务端报输入 {r.usage.prompt_tokens:>6} tok，"
              f"{time.perf_counter() - t0:>4.0f}s | 系统代号{hit('SYS_' + tag)} "
              f"议题代号{hit('TOPIC_' + tag)} 末段代号{hit('END_' + tag)}")
    print("\n判读：末段中而头部丢＝服务端**剪头保尾**；此时报告写的「已纳入 M 份」并不等于模型看到的内容。")


if __name__ == "__main__":
    main()
