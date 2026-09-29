"""企业情报案例构建：知识库「企业内部项目文档」语料 → cases/bi-delivery-risk。

源头语料（~/Downloads/知识库，Obsidian RAG 演示库）含真实机构名的虚构
文档，不能直接进仓库/答辩演示，本脚本做四步加工后落成正式案例二：

1. 精选 6 份数据中台文档（6 种文类、风险梯度分明，约 46KB——
   提示词侧每段截 700 字，全卷 10 份 88KB 过重）；
2. 机构名脱敏（真实银行/券商/央企 → 「某××」客户代号，人员与日期保留，
   手机号/长数字串打码）；
3. 剥离 Obsidian wiki 标记（[[…]] 常断在词中间，只删记号不动正文）；
4. 生成 manifest.yaml（type/credibility 体现信源分层：账目一手 0.8 >
   厂商技术方案 0.7 > 内部汇报 0.5 > 人员清单 0.4）。

重跑幂等：只覆盖本脚本声明的产物文件。用法：
    python scripts/build_bi_case.py [--src 知识库Raw目录]
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CASE_DIR = _REPO_ROOT / "cases" / "bi-delivery-risk"
_DEFAULT_SRC = Path.home() / "Downloads" / "知识库" / "4、企业内部项目文档" / "Raw"

# (源文件名, 产物文件名, 展示标题, manifest type, credibility 覆盖或 None)
SELECTION = [
    ("招商银行_数据中台_技术方案_20240405.md",
     "client_a_proposal_20240405.md",
     "客户A（某股份制商业银行）数据中台V2.0技术方案",
     "report", 0.7),
    ("融创中国_数据中台_项目进度汇报_20260805.md",
     "client_b_progress_20260805.md",
     "客户B（某地产集团）数据中台项目进度汇报",
     "note", 0.55),
    ("中信证券_数据中台_来往账目_20250407.md",
     "client_c_accounts_20250407.md",
     "客户C（某头部券商）数据中台来往账目",
     "other", 0.8),
    ("中国银行_数据中台_来往账目_20250828.md",
     "client_d_accounts_20250828.md",
     "客户D（某国有大行）数据中台来往账目",
     "other", 0.8),
    ("华润置地_数据中台_项目人员清单_20260405.md",
     "client_e_staffing_20260405.md",
     "客户E（某商业地产运营商）数据中台项目人员清单",
     "note", None),
    ("中国电科_数据中台_项目管理计划_20260110.md",
     "client_f_plan_20260110.md",
     "客户F（某电子科技集团）数据中台项目管理计划",
     "note", 0.5),
]

ANONYMIZE = {
    "招商银行": "某股份制商业银行",
    "招行": "某股份制商业银行",
    "中信银行": "某商业银行",
    "中国电子科技集团": "某电子科技集团",
    "融创中国": "某地产集团",
    "融创": "某地产集团",
    "中信证券": "某头部券商",
    "中国银行": "某国有大行",
    "华润置地": "某商业地产运营商",
    "华润": "某商业地产运营商",
    "中国电科": "某电子科技集团",
    "电科": "某电子科技集团",
    # 账目文件里的真实分包商/云厂商（虚构付款明细不能挂在真名下）
    "阿里云计算有限公司": "某云服务商A",
    "阿里云": "某云服务商A",
    "华为技术有限公司": "某服务器供应商B",
    "华为": "某服务器供应商B",
    "北京智服人力资源有限公司": "某人力外包服务商C",
    "北京智联人力服务有限公司": "某人力外包服务商D",
    "北京安恒信息科技股份有限公司": "某安全咨询服务商E",
    "安恒信息": "某安全咨询服务商E",
    "北京信维科技有限公司": "某运维外包服务商F",
    "北京软测科技有限公司": "某测试服务商G",
}

QUESTION = ("星辰数智数据中台业务线交付健康度与风险研判：各客户项目是否存在"
            "延期、回款/坏账或人员流失风险？厂商技术方案的自述指标可信吗？")
TITLE = "企业情报：数据中台交付风险研判（案例二）"


def scrub(text: str) -> str:
    """脱敏 + 剥 wiki 标记。顺序关键：先剥 [[/]]（语料里公司名常被标记
    拦腰截断，如 北京[[智服]]人力资源有限公司，必须先拼回再替换），
    再机构名 → 手机号 → 长数字串。"""
    text = text.replace("[[", "").replace("]]", "")
    for real, anon in ANONYMIZE.items():
        text = text.replace(real, anon)
    text = re.sub(r"1[3-9]\d{9}", lambda m: m.group()[:3] + "****" + m.group()[-4:],
                  text)
    text = re.sub(r"\d{9,}", lambda m: m.group()[:4] + "****", text)
    return text


def build(src_dir: Path) -> None:
    _CASE_DIR.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for src_name, out_name, title, stype, cred in SELECTION:
        raw = (src_dir / src_name).read_text(encoding="utf-8")
        (_CASE_DIR / out_name).write_text(scrub(raw), encoding="utf-8")
        written.append(out_name)

    lines = [f"question: {QUESTION}", f"title: {TITLE}", "sources:"]
    for _, out_name, title, stype, cred in SELECTION:
        lines.append(f"  - file: {out_name}")
        lines.append(f"    title: {title}")
        lines.append(f"    type: {stype}")
        if cred is not None:
            lines.append(f"    credibility: {cred}")
    (_CASE_DIR / "manifest.yaml").write_text("\n".join(lines) + "\n",
                                             encoding="utf-8")

    # 清掉旧版本选中、现已不在清单里的残留（load_case 会摄入目录全部文件）
    for stale in _CASE_DIR.glob("*.md"):
        if stale.name not in written:
            stale.unlink()


def verify(src_dir: Path) -> int:
    """构建后自检：真实机构名与手机号不得残留。"""
    problems: list[str] = []
    for _, out_name, *_ in SELECTION:
        text = (_CASE_DIR / out_name).read_text(encoding="utf-8")
        for real in ANONYMIZE:
            if real in text:
                problems.append(f"{out_name}: 残留机构名「{real}」")
        if re.search(r"1[3-9]\d{9}", text):
            problems.append(f"{out_name}: 残留未打码手机号")
    for p in problems:
        print(f"❌ {p}")
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=_DEFAULT_SRC,
                        help="知识库 Raw 目录（默认 ~/Downloads/知识库/.../Raw）")
    args = parser.parse_args()
    if not args.src.is_dir():
        raise SystemExit(f"源目录不存在：{args.src}")
    build(args.src)
    n_seg = 0
    code = verify(args.src)
    for f in (_CASE_DIR).glob("client_*.md"):
        n_seg += len(re.findall(r"\n\n", f.read_text(encoding="utf-8")))
    size = sum(f.stat().st_size for f in _CASE_DIR.glob("client_*.md"))
    print(f"✅ 案例已生成 {_CASE_DIR}（6 信源，约 {size // 1024}KB）")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
