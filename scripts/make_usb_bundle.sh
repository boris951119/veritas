#!/usr/bin/env bash
# 打 U 盘携带包：zip 排除不可移植与本地产物（.venv 必须现场重建）。
# 用法：bash scripts/make_usb_bundle.sh  →  dist/veritas-<日期>.zip
set -e
cd "$(dirname "$0")/.."

STAMP=$(date +%Y%m%d)
OUT_DIR="dist"
OUT="$OUT_DIR/veritas-$STAMP.zip"
mkdir -p "$OUT_DIR"
rm -f "$OUT"

zip -rq "$OUT" . \
    -x "*/.venv/*" ".venv/*" \
    -x "*/__pycache__/*" "*.pyc" \
    -x "cases/*/out/*" "cases/*/out_offline/*" \
    -x "dist/*" \
    -x "*/.pytest_cache/*" ".pytest_cache/*"

echo "打包完成: $OUT ($(du -h "$OUT" | cut -f1))"
echo "拷到 U 盘后，现场按 AGENTS.md 部署（或直接跑 setup-windows.bat / setup-mac.sh）"
