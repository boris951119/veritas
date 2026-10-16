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
