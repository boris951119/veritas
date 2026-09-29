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

# 敏感与本地产物一律排除：.env/config.json 可含真实密钥（明文 key
# 绝不进携带包——曾因清单漏项把 .env 打进 zip，视为事故修复）；
# .git 是历史记录纯膨胀；密钥由现场按 AGENTS.md 第 4 步另行配置。
zip -rq "$OUT" . \
    -x "*/.venv/*" ".venv/*" \
    -x "*/.git/*" ".git/*" ".git" \
    -x "*/__pycache__/*" "*.pyc" \
    -x "cases/*/out/*" "cases/*/out_offline/*" \
    -x "dist/*" \
    -x "*/.pytest_cache/*" ".pytest_cache/*" \
    -x ".env" "*/.env" \
    -x "config.json" "*/config.json" \
    -x ".DS_Store" "*/.DS_Store"

echo "打包完成: $OUT ($(du -h "$OUT" | cut -f1))"
echo "拷到 U 盘后，现场按 AGENTS.md 部署（或直接跑 setup-windows.bat / setup-mac.sh）"
