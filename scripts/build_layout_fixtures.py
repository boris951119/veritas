#!/usr/bin/env python3
"""生成版式难例 PDF（ASCII 表，跨页/无表头续页/多表），供 layout eval 使用。

不依赖 reportlab：手写最小 PDF + Helvetica。大体积上市年报不入库。
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_OUT = _ROOT / "eval" / "layout" / "fixtures"


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _page_content(lines: list[str], start_y: int = 750) -> str:
    parts = ["BT", "/F1 10 Tf", "14 TL"]
    y = start_y
    for i, line in enumerate(lines):
        if i == 0:
            parts.append(f"50 {y} Td ({_escape(line)}) Tj")
        else:
            parts.append(f"T* ({_escape(line)}) Tj")
    parts.append("ET")
    return "\n".join(parts)


def write_pdf(path: Path, pages: list[list[str]]) -> None:
    """pages: 每页若干文本行。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_pdf_assembled(path, pages)


def _write_pdf_assembled(path: Path, pages: list[list[str]]) -> None:
    """组装：1=Catalog 2=Pages 3=Font 然后 content/page 对。"""
    chunks: list[str] = []
    # We'll build object list as strings
    objs: list[str] = []
    objs.append("")  # 1-index
    objs.append("<< /Type /Catalog /Pages 2 0 R >>")
    objs.append("PLACEHOLDER_PAGES")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    content_ids: list[int] = []
    for lines in pages:
        stream = _page_content(lines)
        raw = stream.encode("latin-1", errors="replace")
        objs.append(
            f"<< /Length {len(raw)} >>\nstream\n{stream}\nendstream"
        )
        content_ids.append(len(objs) - 1)

    page_ids: list[int] = []
    for cid in content_ids:
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {cid} 0 R "
            f"/Resources << /Font << /F1 3 0 R >> >> >>"
        )
        page_ids.append(len(objs) - 1)

    kids = " ".join(f"{i} 0 R" for i in page_ids)
    objs[2] = (
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>"
    )

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i in range(1, len(objs)):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode("ascii"))
        out.extend(objs[i].encode("latin-1", errors="replace"))
        out.extend(b"\nendobj\n")
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objs)}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for i in range(1, len(objs)):
        out.extend(f"{offsets[i]:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(objs)} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(bytes(out))


def main() -> None:
    _OUT.mkdir(parents=True, exist_ok=True)

    # L01: 单页完整表（基线，pypdf 应命中表头+单元格）
    write_pdf(_OUT / "L01_simple_table.pdf", [[
        "Annual Report Table A",
        "Item | Amount | Unit",
        "Revenue | 1280 | CNY_million",
        "Cash | 512 | CNY_million",
    ]])

    # L02: 跨页——第 1 页有表头，第 2 页只有数据行（无表头）
    write_pdf(_OUT / "L02_cross_page_no_header.pdf", [
        [
            "Balance Sheet Cont",
            "Account | Debit | Credit",
            "Cash | 100 | 0",
            "AR | 200 | 0",
        ],
        [
            # continuation page — no header row
            "Inventory | 300 | 0",
            "AP | 0 | 150",
            "Equity | 0 | 450",
        ],
    ])

    # L03: 多表混排
    write_pdf(_OUT / "L03_multi_table.pdf", [[
        "Table One KPIs",
        "Metric | Value",
        "Yield | 40_percent",
        "",
        "Table Two Costs",
        "CostItem | Value",
        "Capex | 9800",
    ]])

    # L04: 宽「横版」感——超长行（模拟横表被抽成乱序行）
    write_pdf(_OUT / "L04_wide_row.pdf", [[
        "Wide row simulation landscape-like",
        "ColA ColB ColC ColD ColE ColF ColG ColH",
        "v1 v2 v3 v4 v5 v6 v7 MARKER_WIDE_99",
    ]])

    # L05: 几乎空页 + 尾页数字（抽字脆弱）
    write_pdf(_OUT / "L05_sparse_pages.pdf", [
        ["Title Only Page"],
        ["", "", "BuriedFigure 777.7"],
    ])

    # L06–L08: 重复结构变体（扩展到 8 份难例）
    write_pdf(_OUT / "L06_receivable_synonym.pdf", [[
        "Accounts Receivable aging",
        "Bucket | Amount",
        "0_30 | 120",
        "Overdue | 88",
    ]])
    write_pdf(_OUT / "L07_footnote_table.pdf", [[
        "Notes to financial statements",
        "Note | Text",
        "3.1 | Contingent liability 42m",
        "* amounts in CNY million",
    ]])
    write_pdf(_OUT / "L08_two_page_header_repeat.pdf", [
        [
            "Segment Revenue",
            "Segment | 2024 | 2025",
            "Auto | 10 | 12",
        ],
        [
            "Segment | 2024 | 2025",
            "Energy | 8 | 9",
            "TOTAL | 18 | 21",
        ],
    ])

    print(f"Wrote fixtures → {_OUT}")


if __name__ == "__main__":
    main()
