"""
pyreshape_for_notion.core.notion_cleanup

Notion インポートを失敗させるノイズを除去するためのモジュール。

なぜ必要か (pcp_017 のデバッグ結論より):
  AI サービス、特に Claude のエクスポートには、思考ブロック (extended
  thinking) やツール使用 (コード実行・ウェブ検索) の痕跡が、
      ```
      This block is not supported on your current device yet.
      ```
  というプレースホルダのコードフェンスとして書き出されている。
  これらが本文と入り組むと、コードフェンスの開閉境界がずれて
  文書構造全体が崩れ、Notion のパーサーがインポート全体を拒否する。

  加えて、ブロック数式 $$...$$ は Notion の Markdown インポートでは
  確実にはサポートされないため、これも失敗要因になり得る。

  このモジュールは、上記の問題を起こすパターンを除去・変換することで、
  Notion インポート可能な Markdown を生成する。

設計方針:
  - 純粋なテキスト → テキストの変換に徹し、副作用を持たない
  - 統計情報を返り値で返し、何件除去・変換したか追跡できる
  - 既定動作は「安全側」(問題を起こすパターンを除去) で、
    詳細はオプションで制御できる

呼び出し方:
  - 既定では core.notion_md.conversation_to_notion_md が内部で呼ぶ
  - 個別に使う場合: notion_cleanup.clean_for_notion(text)
"""

from __future__ import annotations

import re
from typing import TypedDict


class CleanupStats(TypedDict):
    """clean_for_notion の統計情報。"""
    unsupported_removed: int   # 除去した "This block is not supported" ブロック数
    block_math_converted: int  # inline code に変換した $$...$$ ブロック数


# プレースホルダ文字列 (Claude エクスポート由来の思考/ツールブロックの痕跡)
_UNSUPPORTED_MARKER = "This block is not supported on your current device yet."
# 末尾の "yet." を緩めに照合するための部分一致用キー
_UNSUPPORTED_KEY = "This block is not supported"

# コードフェンス検出 (``` で始まる行。言語指定の有無は問わない)
_FENCE_RE = re.compile(r"^\s*```")
# ブロック数式 $$ ... $$
_BLOCK_MATH_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)


def _remove_unsupported_blocks(text: str) -> tuple[str, int]:
    """
    "This block is not supported..." を含むコードフェンスブロックを除去する。
    プレースホルダは通常 1〜3 行のごく短いブロックなので、長すぎるブロックは
    通常のコードブロックとみなして残す (本文に偶然この文字列を含む場合の保護)。
    """
    lines = text.splitlines()
    out: list[str] = []
    removed = 0
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        if _FENCE_RE.match(ln):
            # フェンス開始候補: 閉じフェンスまで本文を収集
            j = i + 1
            body: list[str] = []
            while j < n and not _FENCE_RE.match(lines[j]):
                body.append(lines[j])
                j += 1
            body_text = "\n".join(body).strip()

            if _UNSUPPORTED_KEY in body_text and len(body) <= 3:
                # このブロックを丸ごと除去
                removed += 1
                i = j + 1
                continue

            # 通常のコードブロックとして保持
            out.append(ln)
            out.extend(body)
            if j < n:
                out.append(lines[j])
            i = j + 1
            continue

        out.append(ln)
        i += 1

    return "\n".join(out), removed


def _convert_block_math(text: str) -> tuple[str, int]:
    """
    ブロック数式 $$...$$ を inline code `...` に変換する。
    Notion の Markdown インポートはブロック数式を確実にはサポートしないため、
    数式の中身は残しつつパーサーを壊さない形にする。
    """
    count = 0

    def _repl(m: re.Match) -> str:
        nonlocal count
        count += 1
        return f"`{m.group(1).strip()}`"

    return _BLOCK_MATH_RE.sub(_repl, text), count


def _collapse_blank_lines(text: str) -> str:
    """3 行以上の連続空行を 2 行に圧縮する。"""
    return re.sub(r"\n{3,}", "\n\n", text)


def _ensure_blank_around_hr(text: str) -> str:
    """水平線 --- の前後に空行を確保する (setext 見出し化の予防も兼ねる)。"""
    lines = text.splitlines()
    out: list[str] = []
    for k, ln in enumerate(lines):
        if ln.strip() == "---":
            if out and out[-1].strip() != "":
                out.append("")
            out.append(ln)
            if k + 1 < len(lines) and lines[k + 1].strip() != "":
                out.append("")
        else:
            out.append(ln)
    return "\n".join(out)


def clean_for_notion(
    text: str,
    remove_unsupported: bool = True,
    convert_block_math: bool = True,
    normalize_blanks: bool = True,
) -> tuple[str, CleanupStats]:
    """
    Notion インポートを失敗させるノイズを除去・変換する。

    引数:
      text                : 入力 Markdown
      remove_unsupported  : True なら "This block is not supported..." を除去
      convert_block_math  : True なら $$...$$ を inline code `...` に変換
      normalize_blanks    : True なら連続空行の圧縮と水平線周辺の空行確保を行う

    返り値:
      (クリーニング後のテキスト, 統計情報)
    """
    stats: CleanupStats = {
        "unsupported_removed": 0,
        "block_math_converted": 0,
    }

    if remove_unsupported:
        text, n = _remove_unsupported_blocks(text)
        stats["unsupported_removed"] = n

    if convert_block_math:
        text, n = _convert_block_math(text)
        stats["block_math_converted"] = n

    if normalize_blanks:
        text = _collapse_blank_lines(text)
        text = _ensure_blank_around_hr(text)
        text = _collapse_blank_lines(text)

    # 末尾を必ず単一改行で終える
    return text.rstrip() + "\n", stats
