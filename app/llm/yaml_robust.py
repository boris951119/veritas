"""容错 YAML 加载器（移植自 token-burner acceptance_compile.load_yaml_robust）。

外部 YAML（案例 manifest、第三方提交的资料清单）实测存在缩进硬伤。
策略：让 PyYAML 报错定位坏行，逐行把该行缩进回退到同块兄弟基准
（前一行是 '- ' 序列项则 +2，否则取前一行缩进），循环直至解析成功
或无可进展（上限 400 次）。永不猜改正常行；无法自愈时返回空 dict
显式降级，不抛异常打断管线。
"""

from __future__ import annotations

from pathlib import Path


def load_yaml_robust(path: Path) -> dict:
    import yaml

    text = path.read_text(encoding="utf-8")
    seen: set[tuple[int, int]] = set()
    for _ in range(400):
        try:
            data = yaml.safe_load(text)
            return data if isinstance(data, dict) else {}
        except yaml.YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            if mark is None:
                return {}
            lines = text.split("\n")
            i = int(mark.line)
            if i >= len(lines):
                return {}
            cur = lines[i]
            cur_ind = len(cur) - len(cur.lstrip())
            j = i - 1
            while j >= 0 and not lines[j].strip():
                j -= 1
            if j < 0:
                return {}
            prev = lines[j]
            prev_ind = len(prev) - len(prev.lstrip())
            if cur_ind <= prev_ind:
                return {}          # 损伤不在缩进层级，交空降级
            new_ind = (prev_ind + 2 if prev.lstrip().startswith("-")
                       else prev_ind)
            if (i, cur_ind) in seen or cur_ind == new_ind:
                return {}          # 无进展，防死循环
            seen.add((i, cur_ind))
            lines[i] = " " * new_ind + cur.lstrip()
            text = "\n".join(lines)
    return {}
