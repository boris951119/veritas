#!/bin/bash
# 双击启动。无外网时只使用 vendor/wheels/macosx。
set -e
cd "$(dirname "$0")"
ROOT="$(pwd)"
WHEELS="$ROOT/vendor/wheels/macosx"
PY=""

pick_python() {
  local cand ver
  for cand in "$ROOT/.venv/bin/python" \
      /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 \
      /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11 \
      /usr/bin/python3 python3; do
    if [ -x "$cand" ] || command -v "$cand" >/dev/null 2>&1; then
      ver=$("$cand" -c 'import sys; print(sys.version_info>=(3,10))' 2>/dev/null || true)
      if [ "$ver" = "True" ]; then PY="$cand"; return 0; fi
    fi
  done
  return 1
}

if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
elif pick_python; then
  echo "[1] 使用 $PY 建虚拟环境"
  "$PY" -m venv "$ROOT/.venv"
  PY="$ROOT/.venv/bin/python"
else
  PKG=$(ls "$ROOT"/vendor/python/python-*-macos11.pkg 2>/dev/null | head -1 || true)
  echo "[错误] 未找到 Python 3.10+。"
  if [ -n "$PKG" ]; then
    echo "正在打开离线安装包（装完后请再双击本启动器）："
    echo "  $PKG"
    open "$PKG"
  else
    echo "包内没有 macOS 安装包。请使用带 vendor/python 的完整离线包。"
  fi
  read -r -p "按回车关闭…" _
  exit 1
fi

if [ ! -d "$WHEELS" ]; then
  echo "[错误] 缺少 $WHEELS"
  echo "现场不能临时下载。请换带 vendor/wheels 的完整包。"
  read -r -p "按回车关闭…" _
  exit 1
fi

echo "[2] 从包内安装依赖（不访问外网）"
"$PY" "$ROOT/scripts/offline_install.py"
echo "[3] 打开工作台 http://127.0.0.1:8765/"
export VERITAS_CHAIN_KEY="${VERITAS_CHAIN_KEY:-veritas-contest-demo-hmac}"
(sleep 1; open "http://127.0.0.1:8765/") &
exec "$PY" -m app.server --port 8765
