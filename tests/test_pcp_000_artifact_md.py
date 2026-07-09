"""
tests/test_pcp_000_artifact_md.py

pcp_000: Claude Artifact の md を Notion へ取り込む機能の回帰テスト。

観点:
  1. mathsafe のセグメント分解が原文を完全復元する (無損失の不変条件)
  2. 保護領域 (フェンス・インラインコード・``\\$``) を数式と誤認しない
  3. 数式のコード化・数式ブロックの復元
  4. notion_blocks が equation ブロック / equation リッチテキストを生成する
  5. 既存プラットフォーム (chatgpt/claude/gemini) に影響がない
"""

from __future__ import annotations

import pytest

from pyreshape_for_notion.core import mathsafe
from pyreshape_for_notion import artifact


# ============================================================
# 1. 無損失の不変条件
# ============================================================
SAMPLES = [
    "ふつうの文。",
    r"インライン $x^{2}$ と $4 \times 4$ 行列。",
    "ブロック:\n\n$$\n\\varepsilon(\\mathtt{00}) = (1,1)\n$$\n\n以上。",
    "コード `\\mathsf T` は数式ではない。",
    "```python\nx = '$not math$'\n```\n",
    r"価格は \$100 です。",
    "折り返す $f_{1}(\\lnot x^{-}),\\\nf_{2}(\\lnot x^{+})$ 数式。",
    r"標準デリミタ \(a+b\) と \[c+d\]。",
    "| 字面 | 処置 |\n|---|---|\n| $^{\\mathsf T}$ | 改記 |\n",
]


@pytest.mark.parametrize("src", SAMPLES)
def test_segments_are_lossless(src):
    assert mathsafe.reassemble(mathsafe.iter_segments(src)) == src


def test_fence_content_is_not_scanned():
    src = "```python\nprice = '$x$'\n```\n"
    segs = mathsafe.iter_segments(src)
    assert [s.kind for s in segs] == ["fence"]
    assert not any(s.is_math for s in segs)


def test_inline_code_is_not_scanned():
    segs = mathsafe.iter_segments("`\\mathsf T` → `\\intercal`")
    assert not any(s.is_math for s in segs)
    assert sum(s.kind == "inline_code" for s in segs) == 2


def test_escaped_dollar_is_not_math():
    segs = mathsafe.iter_segments(r"\$100 と \$200")
    assert not any(s.is_math for s in segs)


def test_dollar_followed_by_digit_is_math_not_currency():
    # ``$4 \times 4$`` は通貨ではなく数式。通貨ヒューリスティクスを入れない根拠。
    segs = mathsafe.iter_segments(r"$4 \times 4$ 行列")
    math = [s for s in segs if s.is_math]
    assert len(math) == 1 and math[0].content == r"4 \times 4"


def test_multiline_inline_math():
    src = "左辺 $g(-x, -y) = (f_{1},\\\nf_{2})$ である"
    math = [s for s in mathsafe.iter_segments(src) if s.kind == "math_inline"]
    assert len(math) == 1
    assert "\n" in math[0].content


def test_unclosed_dollar_stays_text():
    segs = mathsafe.iter_segments("残高は $ である")
    assert not any(s.is_math for s in segs)


# ============================================================
# 2. md → md 書き換え
# ============================================================
def test_inline_math_becomes_inline_code():
    out, st = artifact.rewrite_for_notion("値は $\\mathbf{m}$ です。")
    assert out.strip() == "値は `$\\mathbf{m}$` です。"
    assert st.math_inline == 1


def test_inline_math_without_dollar():
    out, _ = artifact.rewrite_for_notion("値は $\\mathbf{m}$ です。", keep_dollar=False)
    assert out.strip() == "値は `\\mathbf{m}` です。"


def test_block_math_becomes_latex_fence():
    src = "前文\n\n$$\n\\emptyset \\mapsto \\mathtt{00}\n$$\n\n後文\n"
    out, st = artifact.rewrite_for_notion(src)
    assert "```latex" in out
    assert "\\emptyset \\mapsto \\mathtt{00}" in out
    assert "$$" not in out
    assert st.math_block == 1


def test_multiline_inline_math_is_flattened():
    src = "左辺 $g(-x),\\\nf_{2}(x)$ である"
    out, _ = artifact.rewrite_for_notion(src)
    assert "\n" not in out.strip()
    assert "`$g(-x),\\ f_{2}(x)$`" in out


def test_latex_standard_delimiters_are_absorbed():
    out, st = artifact.rewrite_for_notion(r"式 \(a+b\) と \[c+d\] 。")
    assert st.latex_delims_normalized == 2
    assert "\\(" not in out and "\\[" not in out


def test_headings_demoted_beyond_h3():
    out, st = artifact.rewrite_for_notion("#### 深い見出し\n")
    assert out.strip() == "**深い見出し**"
    assert st.headings_demoted == 1


def test_table_pipes_escaped():
    src = "| a | b |\n|---|---|\n| $|x| = 1$ | y |\n"
    out, st = artifact.rewrite_for_notion(src)
    assert st.table_pipes_escaped == 2
    assert r"\|x\|" in out


def test_unsupported_block_removed():
    src = "本文\n\n```\nThis block is not supported on your current device yet.\n```\n\n続き\n"
    out, st = artifact.rewrite_for_notion(src)
    assert st.unsupported_removed == 1
    assert "not supported" not in out


def test_math_mode_keep_is_identity_on_math():
    out, _ = artifact.rewrite_for_notion("$x^2$", math_mode="keep")
    assert out.strip() == "$x^2$"


def test_math_mode_invalid():
    with pytest.raises(ValueError):
        artifact.rewrite_for_notion("x", math_mode="bogus")


def test_code_fence_untouched():
    src = "```python\ns = '$x$'\n```\n"
    out, st = artifact.rewrite_for_notion(src)
    assert "s = '$x$'" in out
    assert st.math_inline == 0


# ============================================================
# 3. md → Notion blocks
# ============================================================
def test_block_math_becomes_equation_block():
    blocks = artifact.markdown_to_blocks("$$\nx^{2} + y^{2}\n$$\n")
    assert blocks[0]["type"] == "equation"
    assert blocks[0]["equation"]["expression"] == "x^{2} + y^{2}"


def test_latex_fence_restored_to_equation_block():
    blocks = artifact.markdown_to_blocks("```latex\nE = mc^{2}\n```\n")
    assert blocks[0]["type"] == "equation"
    assert blocks[0]["equation"]["expression"] == "E = mc^{2}"


def test_inline_math_becomes_equation_rich_text():
    blocks = artifact.markdown_to_blocks("値は $\\mathbf{m}$ です。")
    rts = blocks[0]["paragraph"]["rich_text"]
    kinds = [r["type"] for r in rts]
    assert "equation" in kinds
    eq = next(r for r in rts if r["type"] == "equation")
    assert eq["equation"]["expression"] == "\\mathbf{m}"


def test_bold_wrapping_equation_keeps_annotation():
    blocks = artifact.markdown_to_blocks("**$^{\\intercal}$ へ改記**")
    rts = blocks[0]["paragraph"]["rich_text"]
    eq = next(r for r in rts if r["type"] == "equation")
    assert eq["annotations"]["bold"] is True


def test_underscore_is_not_italic():
    blocks = artifact.markdown_to_blocks("来歴 pcp_002_008 による。")
    rts = blocks[0]["paragraph"]["rich_text"]
    assert all(not r["annotations"]["italic"] for r in rts)
    assert "pcp_002_008" in "".join(r["text"]["content"] for r in rts)


def test_table_block():
    src = "| 字面 | 処置 |\n|---|---|\n| $T$ | 維持 |\n"
    blocks = artifact.markdown_to_blocks(src)
    assert blocks[0]["type"] == "table"
    tbl = blocks[0]["table"]
    assert tbl["table_width"] == 2 and tbl["has_column_header"] is True
    cell = tbl["children"][1]["table_row"]["cells"][0]
    assert cell[0]["type"] == "equation"


def test_escaped_pipe_in_table_cell():
    src = "| a | b |\n|---|---|\n| x \\| y | z |\n"
    blocks = artifact.markdown_to_blocks(src)
    cells = blocks[0]["table"]["children"][1]["table_row"]["cells"]
    assert len(cells) == 2
    assert "x | y" in cells[0][0]["text"]["content"]


def test_headings_and_divider():
    blocks = artifact.markdown_to_blocks("# A\n\n## B\n\n---\n\n#### D\n")
    types = [b["type"] for b in blocks]
    assert types == ["heading_1", "heading_2", "divider", "paragraph"]
    assert blocks[3]["paragraph"]["rich_text"][0]["annotations"]["bold"] is True


def test_skip_first_h1():
    blocks = artifact.markdown_to_blocks("# タイトル\n\n本文\n", skip_first_h1=True)
    assert [b["type"] for b in blocks] == ["paragraph"]


def test_cjk_paragraphs_joined_without_space():
    blocks = artifact.markdown_to_blocks("これは日本語の\n折り返し行です。\n")
    content = "".join(r["text"]["content"] for r in blocks[0]["paragraph"]["rich_text"])
    assert content == "これは日本語の折り返し行です。"


def test_ascii_paragraphs_joined_with_space():
    blocks = artifact.markdown_to_blocks("hello\nworld\n")
    content = "".join(r["text"]["content"] for r in blocks[0]["paragraph"]["rich_text"])
    assert content == "hello world"


def test_code_block_language_normalized():
    blocks = artifact.markdown_to_blocks("```py\nx = 1\n```\n")
    assert blocks[0]["type"] == "code"
    assert blocks[0]["code"]["language"] == "python"


def test_unknown_language_falls_back():
    blocks = artifact.markdown_to_blocks("```wat\nfoo\n```\n")
    assert blocks[0]["code"]["language"] == "plain text"


def test_rich_text_length_cap():
    blocks = artifact.markdown_to_blocks("あ" * 4500)
    rts = blocks[0]["paragraph"]["rich_text"]
    assert all(len(r["text"]["content"]) <= artifact.MAX_RICH_TEXT for r in rts)
    assert len(rts) == 3


def test_chunk_blocks():
    blocks = [{"i": k} for k in range(250)]
    chunks = artifact.chunk_blocks(blocks)
    assert [len(c) for c in chunks] == [100, 100, 50]


def test_extract_title():
    assert artifact.extract_title("# CBM 形式枠組み\n\n本文") == "CBM 形式枠組み"
    assert artifact.extract_title("本文のみ") == "Untitled"


def test_make_page_payload():
    blocks = artifact.markdown_to_blocks("# T\n\n$$\nx\n$$\n", skip_first_h1=True)
    p = artifact.make_page_payload("PAGEID", "T", blocks)
    assert p["parent"]["page_id"] == "PAGEID"
    assert p["properties"]["title"]["title"][0]["text"]["content"] == "T"
    assert p["children"][0]["type"] == "equation"


# ============================================================
# 4. 既存経路への非干渉
# ============================================================
def test_existing_notion_cleanup_untouched():
    from pyreshape_for_notion.core import notion_cleanup
    out, st = notion_cleanup.clean_for_notion("$$\nx\n$$\n")
    assert "$$" in out                      # 既定で保持 (0.5.5 の挙動)
    assert st["block_math_converted"] == 0


def test_round_trip_code_mode_to_blocks():
    """md→md (code) → md→blocks で数式が equation に戻ることを確認。"""
    src = "式 $x^{2}$ と\n\n$$\ny = ax + b\n$$\n"
    mid, _ = artifact.rewrite_for_notion(src)
    blocks = artifact.markdown_to_blocks(mid)
    types = [b["type"] for b in blocks]
    assert "equation" in types
    para = blocks[0]["paragraph"]["rich_text"]
    # インラインコードに退避した ``$x^{2}$`` は equation として復元される
    assert any(r["type"] == "equation" for r in para)
