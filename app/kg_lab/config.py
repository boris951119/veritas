"""主线桩：不依赖 vault 路径。"""
from pathlib import Path
VAULT_ROOT = Path(__file__).resolve().parents[2] / ".kg_lab_vault"
