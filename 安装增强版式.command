#!/bin/bash
set -e
cd "$(dirname "$0")"
PY=""
if [ -x .venv/bin/python ]; then PY=".venv/bin/python"
elif [ -x .runtime/python.exe ]; then PY=".runtime/python.exe"
fi
if [ -z "$PY" ]; then
  echo "请先双击「启动工作台」完成基础安装。"
  read -r -p "按回车关闭…" _
  exit 1
fi
echo "从包内安装 Docling（不访问外网）。装不上不影响默认演示。"
"$PY" scripts/offline_install.py --docling
read -r -p "按回车关闭…" _
