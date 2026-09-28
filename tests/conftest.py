import sys
from pathlib import Path

# 让 tests/ 之外的 app 包可导入（pytest rootdir 无包安装时的兜底）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
