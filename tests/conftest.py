import os
import sys
from pathlib import Path

# 让 tests/ 之外的 app 包可导入（pytest rootdir 无包安装时的兜底）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# litellm 一被 import 就去 raw.githubusercontent.com 拉模型价格表；本机网络下
# 这一发要超时 ~10 秒才回落到本地备份（2026-10-13 门禁从 2.8s 涨到 14s 实测到此）。
# 显式要用本地内置表，测试启动时间回到秒级。
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

# 测试会话禁真调用：任何忘了注入假客户端的调用会当场报错，而不是静默
# 拿 .env 里的网关 key 花钱（详见 app/llm/model_client.RealCallGuardedError）。
# 生产路径不上膛——python -m app.pipeline / 工作台 / MCP run_judgment 行为不变。
from app.llm.model_client import arm_no_real_calls  # noqa: E402

arm_no_real_calls()
