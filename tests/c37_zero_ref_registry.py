"""C-37 件⑤：scripts/ 根零引用豁免登记表（纯数据模块）。

本模块**只**承载 `SCRIPT_ZERO_REF_EXEMPTIONS` 常量，不含扫描逻辑。

排除口径（与脚本自身同级）：
- 引用面枚举＝`git ls-files`（tracked）。
- 扫描时排除叙事面：`docs/HANDOFF.md`／`docs/handoff-archive.md`／
  `docs/architecture-*.html`（架构图两种 stem 都算＝10-26 前的全景图 map、
  10-27 起的步骤树 tree；换图名不开新的洗白口）
  以及**本登记模块** `tests/c37_zero_ref_registry.py`。
- 为什么登记模块必须排除：表内键就是脚本文件名字面量；一旦本文件被跟踪且
  计入引用面，四个名字会立刻被判「有引用」→ live 空 → 双向相等恒红
  （R-C37-5／交付态 `3 failed, 906 passed` 的根因）。
- 因此「往本模块写 `from scripts.<stem> import …`」也**不算引用**
  （排除面本身要有牙＝刀⑨）；真引用必须写进操作／决策面
  （AGENTS／dev-protocol／dev-journal）或其它非排除的 tracked 文件（刀⑦b）。

退表：脚本挂上真实调用点或删脚本后，从本表删掉对应键。
"""
from __future__ import annotations

# 名字 → 为什么留着 / 怎么退表（内容冻结；只许搬家，不许改键集合语义）
SCRIPT_ZERO_REF_EXEMPTIONS: dict[str, str] = {
    "gen_eval_questions.py": (
        "B4 评测集 v3 出题工具；评测集已固化进 eval/＝四个里最该处置的一个。"
        "退表＝挂真实调用点或删脚本。"
    ),
    "local_retrieval_smoke.py": (
        "10-19 为 C-19 写的离线检索抽检。退表＝挂真实调用点或删脚本。"
    ),
    "measure_capacity.py": (
        "C-7 容量实测探针；docstring 自述架构师用不进 tests。"
        "退表＝把跑法写进 docs/dev-journal.md 或改成测试调用。"
    ),
    "probe_source_dedup.py": (
        "C-14 工单「实测前提」的数字来源。"
        "退表＝把跑法写进 docs/dev-journal.md。"
    ),
}
