"""路径与本机模型默认值（仅 kg_lab；不读／不写生产 .env 开关）。"""

from __future__ import annotations

from pathlib import Path

EXP_ROOT = Path(__file__).resolve().parents[2]
VAULT_ROOT = EXP_ROOT / "vaults" / "kg-lab"
SLICES_DIR = VAULT_ROOT / "slices"
SUMMARIES_DIR = VAULT_ROOT / "summaries"
ENTITIES_DIR = VAULT_ROOT / "entities"
EVENTS_DIR = VAULT_ROOT / "events"
EDGES_DIR = VAULT_ROOT / "edges"
ARTIFACTS = EXP_ROOT / "artifacts" / "kg-index"
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
