#!/usr/bin/env bash
# veritas macOS 一键环境：venv + 依赖 + 全量测试自检（零 key 全绿）
set -e
cd "$(dirname "$0")"

PY=""
for cand in /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 \
            /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
        ver=$("$cand" -c 'import sys;print(sys.version_info[:2] >= (3, 10))')
        if [ "$ver" = "True" ]; then PY="$cand"; break; fi
    fi
done
[ -n "$PY" ] || { echo "[错误] 未找到 Python 3.10+，请 brew install python@3.12"; exit 1; }
echo "[1/4] Python: $($PY --version)"

echo "[2/4] 建 venv 并装依赖"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt litellm \
    || .venv/bin/pip install -q -r requirements.txt litellm \
        -i https://pypi.tuna.tsinghua.edu.cn/simple

echo "[3/4] 全量测试（零 key 全绿）"
.venv/bin/python -m pytest tests -q

echo "[4/4] 完成。离线演示: .venv/bin/python scripts/demo_offline.py"
echo "在线研判: 复制 .env.example 为 .env 填 key 后，"
echo "          .venv/bin/python -m app.pipeline cases/demo-solid-state"
