"""
pyreshape_for_notion.core.pcp_split

Notion 用 Markdown を pcp 単位で複数の小さい MD に分割する (Code_006 相当)。
pcp 数が大きいチャットを Notion AI が処理しきれない問題への対応。
pcp 境界を絶対に跨がず、分割位置がファイル名から一目で分かる。

入力 MD は core.notion_md が出力した形式を前提とする。
"""

from __future__ import annotations

import re
from typing import Any

# v2: pcp は "## pcp_NNN" 見出し。v1 の "- pcp_NNN" 箇条書きも後方互換で受理。
PCP_LINE_RE = re.compile(r"^(?:#{1,6}[ \t]+|- )pcp_(\d{3}(?:_\d{3})*)\s*$")


class Pcp:
    """1 つの pcp ブロック。"""
    def __init__(self, label: str, lines: list[str], begin_lineno: int):
        self.label = label
        self.lines = lines
        first_num = label.split("_", 1)[0]
        self.first_num = int(first_num) if first_num.isdigit() else 0
        self.begin_lineno = begin_lineno


def parse_md(text: str) -> tuple[list[str], list[Pcp]]:
    """MD 文字列を (ヘッダ行群, pcp ブロック群) に分解する。"""
    lines = text.splitlines()
    header_lines: list[str] = []
    pcps: list[Pcp] = []

    cursor = 0
    for i, ln in enumerate(lines):
        if PCP_LINE_RE.match(ln):
            cursor = i
            break
        header_lines.append(ln)
    else:
        return header_lines, []

    current_label: str | None = None
    current_lines: list[str] = []
    current_begin = cursor

    for i in range(cursor, len(lines)):
        ln = lines[i]
        m = PCP_LINE_RE.match(ln)
        if m:
            if current_label is not None:
                pcps.append(Pcp(current_label, current_lines, current_begin))
            current_label = m.group(1)
            current_lines = [ln]
            current_begin = i
        else:
            if current_label is not None:
                current_lines.append(ln)
    if current_label is not None:
        pcps.append(Pcp(current_label, current_lines, current_begin))

    return header_lines, pcps


def build_parts(pcps: list[Pcp], max_per_part: int) -> list[list[Pcp]]:
    if not pcps:
        return []
    return [pcps[i: i + max_per_part] for i in range(0, len(pcps), max_per_part)]


def part_filename(stem: str, part_idx: int, part: list[Pcp]) -> str:
    if not part:
        return f"{stem}__part{part_idx:02d}_empty.md"
    nums = [p.first_num for p in part]
    return f"{stem}__part{part_idx:02d}_pcp{min(nums):03d}-{max(nums):03d}.md"


def split_md_text(
    text: str,
    stem: str,
    src_name: str,
    max_pcps_per_part: int = 25,
) -> list[tuple[str, str]]:
    """
    MD 文字列を pcp 単位で分割し、(出力ファイル名, 内容) のリストを返す。
    pcp が無い場合は元の内容をそのまま 1 件返す (ファイル名は stem.md)。
    """
    header_lines, pcps = parse_md(text)

    if not pcps:
        return [(f"{stem}.md", text)]

    parts = build_parts(pcps, max_pcps_per_part)
    header_text = "\n".join(header_lines).rstrip()
    out: list[tuple[str, str]] = []

    for idx, part in enumerate(parts, start=1):
        out_name = part_filename(stem, idx, part)
        body_lines: list[str] = []
        for p in part:
            body_lines.extend(p.lines)
            if body_lines and body_lines[-1] != "":
                body_lines.append("")

        nums = [p.first_num for p in part]
        front: list[str] = []
        if header_text:
            front.append(header_text)
        front.append("")
        front.append(
            f"_(part {idx} / {len(parts)} : pcp_{min(nums):03d} 〜 "
            f"pcp_{max(nums):03d}, {len(part)} pcps, source: {src_name})_"
        )
        front.append("")

        whole = "\n".join(front + body_lines).rstrip() + "\n"
        out.append((out_name, whole))

    return out
