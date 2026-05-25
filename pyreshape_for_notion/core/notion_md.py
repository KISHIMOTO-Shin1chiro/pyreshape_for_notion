"""
pyreshape_for_notion.core.notion_md  (v2)

正規化済み会話 (NormalizedConv) を Notion 互換 Markdown に変換する。

v2 での主な改善 (pcp_016):
  1. pcp 構造を「箇条書きのインデント」ではなく「Markdown 見出し」で表現する。
     これにより completion 本文を一切インデントせずに済み、本文中の
     見出し (##, ###) や箇条書きの階層が Notion で正しく解釈される。
  2. completion / prompt 本文中の見出しレベルを、pcp 見出しと衝突しないよう
     相対的に繰り下げる (shift)。
  3. 同一の prompt-completion ペアの重複を除去する。

出力構造 (v2):
  # 会話タイトル

  ## pcp_001

  ### A Prompt by User

  (prompt 本文。無インデント。見出しは ##### 以降にシフト)

  ### A Completion by LLM

  (completion 本文。無インデント。見出しも階層も保持)

  ---

旧 v1 の出力 (本文を 4 スペースインデントする方式) は
notion_md_v1_backup.py に保管。
"""

from __future__ import annotations

import re
from typing import Any

from .schema import NormalizedConv, NormalizedMessage, extract_visible_text

# ============================================================
# 定数
# ============================================================
# 会話タイトルを H1 とし、pcp 見出しを H2 (## ) とする。
# 本文中の見出しはシフトせず原文のレベルを保つ既定。
PCP_HEADING_LEVEL = 2
# prompt/completion ラベルは見出しを消費せず太字段落で表現する。
#   → 本文中の見出し (H2, H3) を Notion 見出しとして温存するため。
# 本文中の見出しをこのレベルを基準に繰り下げる下限 (## = H2)
BODY_HEADING_FLOOR = 2
# Markdown 見出しの最大レベル (Notion は H3 まで。それ以深は太字段落化)
MAX_MD_HEADING = 3

PCP_PATTERN = re.compile(r"pcp_(\d{3}(?:_\d{3})*)", re.IGNORECASE)

# 本文中の ATX 見出し行 (先頭の # 〜 ###### + 空白 + 内容)
ATX_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*)$")
CODE_FENCE_LINE_RE = re.compile(r"^\s*(```|~~~)")


# ============================================================
# pcp ラベル抽出
# ============================================================
def extract_pcp_label(text: str) -> str | None:
    m = PCP_PATTERN.search(text or "")
    return m.group(1) if m else None


# ============================================================
# 本文中の見出しレベルをシフトする
# ============================================================
def shift_headings(text: str, floor_level: int = BODY_HEADING_FLOOR) -> str:
    """
    本文中の ATX 見出し (#, ##, ...) のレベルを、pcp/ラベル見出しと
    衝突しないよう繰り下げる。

    元の見出しレベル h を、floor_level を基準に再配置する:
      new_level = floor_level + (h - 1)
    ただし Markdown/Notion の見出し上限を超える分は太字段落に変換する。

    コードフェンス内部の # 始まりの行 (コメント等) は変換しない。
    """
    lines = text.splitlines()
    out: list[str] = []
    in_fence = False

    for line in lines:
        if CODE_FENCE_LINE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue

        m = ATX_HEADING_RE.match(line)
        if not m:
            out.append(line)
            continue

        hashes, content = m.group(1), m.group(2)
        h = len(hashes)
        new_level = floor_level + (h - 1)

        if new_level <= MAX_MD_HEADING:
            out.append("#" * new_level + " " + content)
        else:
            # 見出し上限を超える深さは太字段落として表現
            # (Notion で見出しにならない代わりに、視覚的な強調を保つ)
            content_stripped = content.strip()
            if content_stripped:
                out.append(f"**{content_stripped}**")
            else:
                out.append("")

    return "\n".join(out)


# ============================================================
# human / assistant のペア化 + 重複除去
# ============================================================
def pair_into_pcps(
    msgs: list[NormalizedMessage],
) -> list[tuple[NormalizedMessage, NormalizedMessage | None]]:
    msgs_sorted = sorted(msgs, key=lambda m: m.get("index", 0))
    pcps: list[tuple[NormalizedMessage, NormalizedMessage | None]] = []
    pending: NormalizedMessage | None = None
    for m in msgs_sorted:
        s = m.get("sender")
        if s == "human":
            if pending is not None:
                pcps.append((pending, None))
            pending = m
        elif s == "assistant" and pending is not None:
            pcps.append((pending, m))
            pending = None
    if pending is not None:
        pcps.append((pending, None))
    return pcps


def _pair_signature(
    human: NormalizedMessage,
    assistant: NormalizedMessage | None,
) -> tuple[str, str]:
    """重複判定用の (prompt 本文, completion 本文) の正規化シグネチャ。"""
    p = (extract_visible_text(human) or "").strip()
    c = (extract_visible_text(assistant) or "").strip() if assistant else ""
    return p, c


def dedupe_pcps(
    pcps: list[tuple[NormalizedMessage, NormalizedMessage | None]],
) -> list[tuple[NormalizedMessage, NormalizedMessage | None]]:
    """
    同一の (prompt 本文, completion 本文) を持つペアの重複を除去する。
    Claude エクスポートのツリー分岐・再生成由来の重複に対応。
    最初に出現したペアを残し、以降の同一シグネチャを捨てる。
    """
    seen: set[tuple[str, str]] = set()
    out: list[tuple[NormalizedMessage, NormalizedMessage | None]] = []
    for human, assistant in pcps:
        sig = _pair_signature(human, assistant)
        # prompt も completion も空のペアは無視
        if not sig[0] and not sig[1]:
            continue
        if sig in seen:
            continue
        seen.add(sig)
        out.append((human, assistant))
    return out


# ============================================================
# 会話 → Notion Markdown (v2: 見出しベース)
# ============================================================
def conversation_to_notion_md(
    conv: NormalizedConv,
    fallback_seq_start: int = 0,
    dedupe: bool = True,
    shift_body_headings: bool = False,
) -> str:
    msgs = conv.get("chat_messages", [])
    pcps = pair_into_pcps(msgs)
    if dedupe:
        pcps = dedupe_pcps(pcps)

    out: list[str] = []
    name = conv.get("name") or ""
    if name:
        out.append("# " + name)
        out.append("")

    pcp_h = "#" * PCP_HEADING_LEVEL

    def _body(text: str) -> str:
        return shift_headings(text) if shift_body_headings else text

    auto_seq = fallback_seq_start
    for human, assistant in pcps:
        prompt_text = extract_visible_text(human).rstrip()
        comp_text = extract_visible_text(assistant).rstrip() if assistant else ""

        label = extract_pcp_label(prompt_text)
        if label is None:
            label = f"{auto_seq:03d}"
            auto_seq += 1

        # pcp 見出し (H1)
        out.append(f"{pcp_h} pcp_{label}")
        out.append("")

        # prompt ラベル (太字段落。見出しレベルを消費しない)
        out.append("**A Prompt by User**")
        out.append("")
        out.append(_body(prompt_text))
        out.append("")

        # completion ラベル
        out.append("**A Completion by LLM**")
        out.append("")
        out.append(_body(comp_text))
        out.append("")

        # pcp 区切り
        out.append("---")
        out.append("")

    return "\n".join(out) + "\n"
