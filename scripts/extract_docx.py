"""按文档顺序提取 docx 正文（段落＋表格），零依赖——只解 word/document.xml。

用法：`.venv/bin/python scripts/extract_docx.py <docx 路径>`
官方公布文件在仓库外，见 docs/contest-requirements-S4-2026-10-17.md。
"""
import sys
import zipfile
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def para_text(p):
    parts = []
    for node in p.iter():
        if node.tag == W + "t":
            parts.append(node.text or "")
        elif node.tag == W + "tab":
            parts.append("\t")
        elif node.tag in (W + "br", W + "cr"):
            parts.append("\n")
    return "".join(parts)


def walk(body, out, depth=0):
    for child in body:
        if child.tag == W + "p":
            txt = para_text(child).strip()
            style = child.find(f"{W}pPr/{W}pStyle")
            tag = style.get(W + "val") if style is not None else ""
            if txt:
                prefix = f"[{tag}] " if tag else ""
                out.append("  " * depth + prefix + txt)
        elif child.tag == W + "tbl":
            out.append("  " * depth + "── table ──")
            for row in child.findall(W + "tr"):
                cells = []
                for tc in row.findall(W + "tc"):
                    cell = " / ".join(
                        t for t in (para_text(p).strip() for p in tc.iter(W + "p")) if t
                    )
                    cells.append(cell)
                out.append("  " * depth + "| " + " | ".join(cells))
            out.append("  " * depth + "── end table ──")


def main(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
        names = sorted(n for n in z.namelist() if n.startswith("word/") and n.endswith(".xml"))
    root = ET.fromstring(xml)
    out = []
    body = root.find(W + "body")
    walk(body, out)
    print("\n".join(out))
    print(f"\n=== parts: {len(names)} ===")
    for n in names:
        print(n)


if __name__ == "__main__":
    main(sys.argv[1])
