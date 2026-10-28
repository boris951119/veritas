"""提示词窗口估算闸（零 LLM）：发送前粗估是否超模型上下文。

不做截断、不收窄预算——只给出可进报告的数字与文案素材（C-9 丙）。
密度常数来自本机探针（≈0.69 tok/字 → zh_chars_per_token=1.45），
不是 tiktoken；方向安全：宁可多报超窗、不可漏报。
"""

from __future__ import annotations


def estimate_prompt_window(
    messages: list[dict],
    *,
    window_tokens: int,
    zh_chars_per_token: float,
) -> dict:
    """已渲染 messages + 窗口设定 → 估算结果。

    返回键：est_tokens／window_tokens／overflow_tokens／detail／
    total_chars／checked（False 当 window_tokens<=0）。
    """
    total_chars = 0
    for msg in messages or []:
        content = msg.get("content") if isinstance(msg, dict) else None
        if content is None:
            continue
        total_chars += len(str(content))

    if window_tokens <= 0:
        return {
            "est_tokens": 0,
            "window_tokens": int(window_tokens),
            "overflow_tokens": 0,
            "total_chars": total_chars,
            "checked": False,
            "detail": "模型窗口未检查（model_context_tokens≤0）",
        }

    density = float(zh_chars_per_token) if zh_chars_per_token > 0 else 1.45
    est_tokens = int(total_chars / density)
    overflow = max(0, est_tokens - int(window_tokens))
    overflow_chars = int(round(overflow * density))
    if overflow > 0:
        detail = (
            f"提示词≈{total_chars} 字 ≈{est_tokens} token＞窗口 {window_tokens}"
            f"（按假定窗口），超出约 {overflow} token（≈{overflow_chars} 字）；"
            f"服务端会从提示词头部静默剪掉，角色纪律与研判议题可能未到达模型"
        )
    else:
        detail = (
            f"提示词≈{total_chars} 字 ≈{est_tokens} token，"
            f"未超过假定窗口 {window_tokens}"
        )
    return {
        "est_tokens": est_tokens,
        "window_tokens": int(window_tokens),
        "overflow_tokens": overflow,
        "total_chars": total_chars,
        "checked": True,
        "detail": detail,
    }


def build_window_ledger(
    call_log: list[dict] | None,
    *,
    window_tokens: int | None = None,
) -> dict:
    """C-73：从 call_log（仅含窗口账四键的 chat 腿）聚合成 accounting 账。

    embedding 自 append 的条目没有 server_reported 键 → 跳过（本单故意不并）。
    硬禁：聚合侧也不许用 est 回填 server_prompt_tokens。
    """
    rows_out: list[dict] = []
    densities: list[float] = []
    n_server = 0
    n_over = 0
    max_server: int | None = None
    win = int(window_tokens) if (window_tokens is not None
                                  and int(window_tokens) > 0) else None
    for entry in call_log or []:
        if not isinstance(entry, dict):
            continue
        if "server_reported" not in entry:
            continue  # embedding／旧条目
        chars = int(entry.get("prompt_chars") or 0)
        est = int(entry.get("est_tokens") or 0)
        server = entry.get("server_prompt_tokens")
        reported = bool(entry.get("server_reported")) and server is not None
        over = entry.get("over_window")
        if reported:
            n_server += 1
            srv_i = int(server)
            if max_server is None or srv_i > max_server:
                max_server = srv_i
            if chars > 0 and srv_i > 0:
                densities.append(chars / srv_i)
            if over is True:
                n_over += 1
            ratio: float | None = (est / srv_i) if srv_i > 0 else None
        else:
            ratio = None
        hint = str(entry.get("system_hint") or "")
        leg = hint.strip().splitlines()[0][:40] if hint.strip() else (
            str(entry.get("model") or "chat"))
        rows_out.append({
            "leg": leg,
            "model": entry.get("model"),
            "prompt_chars": chars,
            "est_tokens": est,
            "server_prompt_tokens": server if reported else None,
            "est_over_server": ratio,
            "over_window": over,
            "server_reported": reported,
        })
    min_dens = min(densities) if densities else None
    return {
        "n_calls": len(rows_out),
        "n_server_reported": n_server,
        "max_server_prompt_tokens": max_server,
        "window_tokens": win,
        "min_true_chars_per_token": min_dens,
        "n_over_window": n_over,
        "rows": rows_out,
    }


def format_window_ledger_line(ledger: dict | None) -> str:
    """报告面一行。无真数 ⇒ 必须含「服务端未报，未据此判定」（不许省略该行）。

    禁词：漏检率／召回率。
    """
    led = ledger or {}
    n_server = int(led.get("n_server_reported") or 0)
    n_miss = int(led.get("n_calls") or 0) - n_server
    if n_miss < 0:
        n_miss = 0
    max_srv = led.get("max_server_prompt_tokens")
    win = led.get("window_tokens")
    dens = led.get("min_true_chars_per_token")
    # 估算口径偏＝现密度相对真密度的偏差（有真密度时）
    # 现常量默认 1.45；正＝本地估偏密（高报 token）
    bias_txt = "—"
    if isinstance(dens, (int, float)) and float(dens) > 0:
        # 不从 settings 读，避免报告层耦合；偏置用 1.45 对照真密度
        assumed = 1.45
        bias_pct = (assumed / float(dens) - 1.0) * 100.0
        bias_txt = f"{bias_pct:+.1f}"
    if n_server <= 0 or max_srv is None:
        return (
            "窗口账（服务端真报）：服务端未报，未据此判定"
            f"（未报 {n_miss} 次）"
        )
    win_i = int(win) if win else 0
    if win_i > 0:
        z_pct = 100.0 * float(max_srv) / float(win_i)
        return (
            f"窗口账（服务端真报）：本次最长提示词 {int(max_srv)}／"
            f"窗口 {win_i}（{z_pct:.1f}%）、估算口径偏 {bias_txt}%、"
            f"服务端未报 {n_miss} 次"
        )
    return (
        f"窗口账（服务端真报）：本次最长提示词 {int(max_srv)}／"
        f"窗口未声明、估算口径偏 {bias_txt}%、服务端未报 {n_miss} 次"
    )
