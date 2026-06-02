"""
pcp_022_012 で報告されたバグ (ChatGPT 由来 md で TeX 式が壊れる) に対する
回帰テスト。

修正内容: ChatGPT パーサで LaTeX 標準デリミタを KaTeX 互換に変換する。
  \\(...\\) → $...$    (インライン数式)
  \\[...\\] → $$...$$  (ブロック数式)
さらに、ChatGPT が二重出力する ```tex / ```latex フェンスを除去する。

加えて、core/notion_cleanup.py の convert_block_math の既定が
True から False に変更されたことの検証を含む (現在の Notion は
$$...$$ をブロック数式として認識するため、変換すると逆効果)。

重要: 修正は ChatGPT パーサ内のみで、Claude / Gemini は影響を受けない。
"""

import json
from pathlib import Path

import pytest

from pyreshape_for_notion.chatgpt.parser import (
    _normalize_tex_delimiters,
    normalize_conv,
)
from pyreshape_for_notion.core.notion_md import pair_into_pcps
from pyreshape_for_notion.core.schema import extract_visible_text


# ============================================================
# _normalize_tex_delimiters 単体
# ============================================================
def test_block_delimiter_converted():
    r"""\[ ... \] が $$ ... $$ に変換される。"""
    text = "前\n\n\\[\n\\mathcal{B}_t = \\langle x \\rangle\n\\]\n\n後"
    result = _normalize_tex_delimiters(text)
    assert "$$" in result
    assert "\\[" not in result
    assert "\\]" not in result
    assert "\\mathcal{B}_t = \\langle x \\rangle" in result


def test_inline_delimiter_converted():
    r"""\( ... \) が $ ... $ に変換される。"""
    text = "ここで、\\(\\mathcal{C}_t\\) は集合です。"
    result = _normalize_tex_delimiters(text)
    assert "$\\mathcal{C}_t$" in result
    assert "\\(" not in result
    assert "\\)" not in result


def test_tex_fence_removed():
    r"""```tex フェンスが除去される。"""
    text = '本文\n\n```tex id="abc"\n\\mathrm{sim}(x,y)\n```\n\n後'
    result = _normalize_tex_delimiters(text)
    assert "```tex" not in result
    assert "本文" in result
    assert "後" in result


def test_latex_fence_removed():
    r"""```latex フェンスも除去される。"""
    text = "本文\n\n```latex\n\\alpha + \\beta\n```\n\n後"
    result = _normalize_tex_delimiters(text)
    assert "```latex" not in result
    assert "\\alpha + \\beta" not in result


def test_python_fence_preserved():
    r"""```python など通常のコードブロックは保持される。"""
    text = "```python\nprint('hello')\n```\n"
    result = _normalize_tex_delimiters(text)
    assert "```python" in result
    assert "print('hello')" in result


def test_double_output_collapses_to_one_block():
    r"""\[...\] と ```tex の二重出力 → $$...$$ 一つになる。"""
    text = (
        "本文\n\n"
        "\\[\n\\mathcal{B}_t = \\langle x \\rangle\n\\]\n\n"
        "```tex\n\\[\n\\mathcal{B}_t = \\langle x \\rangle\n\\]\n```\n\n"
        "続き"
    )
    result = _normalize_tex_delimiters(text)
    # $$ が 1 ブロック (= 2 個) だけ残る
    assert result.count("$$") == 2
    assert "```tex" not in result
    # 本文と続きは保たれる
    assert "本文" in result
    assert "続き" in result


def test_inline_does_not_cross_newlines():
    r"""\( ... \) は改行をまたがない (壊れたインラインを誤マッチしない)。"""
    text = "正常: \\(x\\) と \\(y\\)\n\n別段落の \\( 開きだけ"
    result = _normalize_tex_delimiters(text)
    assert "$x$" in result
    assert "$y$" in result
    # 開きだけの行は変換されない
    assert "\\( 開きだけ" in result


def test_empty_text_returns_empty():
    """空文字列はそのまま返す。"""
    assert _normalize_tex_delimiters("") == ""


def test_no_tex_text_unchanged():
    """TeX 表現を含まないテキストは変更されない。"""
    text = "普通の日本語テキストです。\n段落も含めて。"
    assert _normalize_tex_delimiters(text) == text


# ============================================================
# 実 ChatGPT エクスポートでの検証
# ============================================================
def test_real_chatgpt_export_pcp_022_012():
    """実際の ChatGPT エクスポート (GPT-5.5 Pro) で TeX 変換が正しく機能する。"""
    src = Path("/mnt/user-data/uploads/conversations-021.json")
    if not src.exists():
        pytest.skip("テスト用エクスポートが存在しない")

    data = json.load(open(src, encoding="utf-8-sig"))
    target = next(
        (c for c in data if c.get("id", "").startswith("6a17defc")), None,
    )
    if target is None:
        pytest.skip("対象会話が見つからない")

    conv = normalize_conv(target)
    pcps = pair_into_pcps(conv["chat_messages"])
    all_text = "\n".join(extract_visible_text(a) for _, a in pcps if a)

    # 0.5.5 後: \[ \] \( \) は残存ゼロ、```tex / ```latex も残存ゼロ
    assert "\\[" not in all_text
    assert "\\]" not in all_text
    assert "\\(" not in all_text
    assert "\\)" not in all_text
    assert "```tex" not in all_text
    assert "```latex" not in all_text

    # 代わりに $...$ と $$...$$ が出ている
    assert all_text.count("$$") >= 2  # 少なくとも 1 ブロック以上
    # 期待される数式の中身は保たれている
    assert "\\mathcal{B}_t" in all_text


# ============================================================
# 他プラットフォーム (Claude/Gemini) への影響を排除
# ============================================================
def test_claude_parser_not_affected():
    """Claude のパーサが \\(...\\) や \\[...\\] を変換しないことを確認。"""
    from pyreshape_for_notion.claude.parser import normalize_conv as norm_claude

    raw = {
        "uuid": "c1",
        "name": "T",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "chat_messages": [
            {"uuid": "m0", "sender": "human", "index": 0, "text": "q"},
            {
                "uuid": "m1", "sender": "assistant", "index": 1,
                "text": "数式: \\(x = 1\\) と \\[ y = 2 \\]",
            },
        ],
    }
    conv = norm_claude(raw)
    a_text = conv["chat_messages"][1]["text"]
    # Claude では LaTeX デリミタがそのまま保持される (変換しない)
    assert "\\(x = 1\\)" in a_text
    assert "\\[ y = 2 \\]" in a_text


def test_gemini_parser_not_affected(tmp_path):
    """Gemini のパーサも LaTeX デリミタを変換しないことを確認。"""
    from pyreshape_for_notion.gemini.parser import parse_file

    md = (
        "# Gemini Chat Export\n\n"
        "> Exported on: 2026/5/13 10:00\n\n"
        "---\n\n"
        "## 👤 You\n\nq\n\n"
        "## 🤖 Gemini\n\n数式: \\(x = 1\\) と \\[ y = 2 \\]\n\n"
        "---\n"
    )
    f = tmp_path / "2025-12-19_t.md"
    f.write_text(md, encoding="utf-8")

    conv = parse_file(f)
    a_text = conv["chat_messages"][1]["text"]
    assert "\\(x = 1\\)" in a_text
    assert "\\[ y = 2 \\]" in a_text


# ============================================================
# notion_cleanup.convert_block_math のデフォルト変更
# ============================================================
def test_convert_block_math_default_is_false():
    """0.5.5 では convert_block_math の既定が False。"""
    from pyreshape_for_notion.core.notion_cleanup import clean_for_notion

    text = "数式: $$x = 1$$\n"
    cleaned, stats = clean_for_notion(text)
    # 既定では $$ が保持される
    assert "$$x = 1$$" in cleaned
    assert stats["block_math_converted"] == 0


def test_convert_block_math_still_available_via_explicit_arg():
    """旧挙動を明示的に有効化することは可能。"""
    from pyreshape_for_notion.core.notion_cleanup import clean_for_notion

    text = "数式: $$x = 1$$\n"
    cleaned, stats = clean_for_notion(text, convert_block_math=True)
    assert "$$" not in cleaned
    assert "`x = 1`" in cleaned
    assert stats["block_math_converted"] == 1
