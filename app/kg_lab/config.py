"""路径与本机模型默认值（仅 kg_lab；不读／不写生产 .env 开关）。

C-125 端口订正（相对实验仓两处根路径，算法常量逐字同）：
- ``VAULT_ROOT``＝主仓 ``.kg_lab_vault``（gitignore 运行时缓存；
  实验仓摘要在场则暖启动，缺文件由 ``load_summary`` 优雅回退 None）；
- ``ARTIFACTS``＝主仓 ``.kgcache/kg-index``（嵌入缓存，同样 gitignore，
  不进 committed artifacts——产物卫生）。
"""

from __future__ import annotations

from pathlib import Path

EXP_ROOT = Path(__file__).resolve().parents[2]
VAULT_ROOT = EXP_ROOT / ".kg_lab_vault"
SLICES_DIR = VAULT_ROOT / "slices"
SUMMARIES_DIR = VAULT_ROOT / "summaries"
ENTITIES_DIR = VAULT_ROOT / "entities"
EVENTS_DIR = VAULT_ROOT / "events"
EDGES_DIR = VAULT_ROOT / "edges"
ARTIFACTS = EXP_ROOT / ".kgcache" / "kg-index"
DEFAULT_SAMPLES = EXP_ROOT / "data" / "trs-samples"

OLLAMA_HOST = "http://127.0.0.1:11434"
SUMMARY_MODEL = "veritas-qwen3-14b"
EMBED_MODEL = "bge-m3"

# 召回 K（对齐 C-104 主尺）
DEFAULT_K = 7
WIDE_K = 15

# 摘要并发（本机 Ollama）
SUMMARY_WORKERS = 2
SUMMARY_NUM_PREDICT = 420
EMBED_BATCH_CHARS = 1200  # 单段送 embedding 的上限字数
