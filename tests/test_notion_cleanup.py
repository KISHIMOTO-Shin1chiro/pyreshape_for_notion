"""
0.4.0 で導入した notion_cleanup の回帰テスト。
pcp_017 で報告された Notion インポート失敗の原因 (思考ブロック痕跡、
ブロック数式) が、0.4.0 では自動的に防止されることを検証する。
"""

from pyreshape_for_notion.core.notion_cleanup import clean_for_notion
from pyreshape_for_notion.core.notion_md import conversation_to_notion_md
from pyreshape_for_notion.core.schema import make_conversation, make_message


def _conv(prompt: str, completion: str) -> dict:
    return make_conversation(
        uuid="t", name="T",
        messages=[
            make_message(uuid="m0", sender="human", text=prompt, index=0),
            make_message(uuid="m1", sender="assistant", text=completion, index=1),
        ],
    )


# ========== notion_cleanup 単体 ==========

def test_remove_unsupported_block_standalone():
    """'This block is not supported...' を含むフェンスを除去する。"""
    text = "本文\n\n```\nThis block is not supported on your current device yet.\n```\n\n続き\n"
    cleaned, stats = clean_for_notion(text)
    assert "This block is not supported" not in cleaned
    assert stats["unsupported_removed"] == 1


def test_normal_code_block_preserved():
    """通常のコードブロックは保持される。"""
    text = "本文\n\n```python\ndef f():\n    return 42\n```\n"
    cleaned, _ = clean_for_notion(text)
    assert "```python" in cleaned
    assert "def f():" in cleaned
    assert "return 42" in cleaned


def test_block_math_converted():
    """ブロック数式 $$...$$ が inline code に変換される (明示オプション)。"""
    # 0.5.5 で convert_block_math の既定が False に変わったため、
    # 旧挙動のテストでは明示的に True を指定する
    text = "数式: $$a \\odot a = a$$ です。\n"
    cleaned, stats = clean_for_notion(text, convert_block_math=True)
    assert "$$" not in cleaned
    assert "`a \\odot a = a`" in cleaned
    assert stats["block_math_converted"] == 1


def test_block_math_preserved_by_default_0_5_5():
    """0.5.5 既定では $$...$$ がブロック数式として保持される。"""
    text = "数式: $$a \\odot a = a$$ です。\n"
    cleaned, stats = clean_for_notion(text)  # 既定 (False)
    assert "$$a \\odot a = a$$" in cleaned
    assert stats["block_math_converted"] == 0


def test_multiple_unsupported_and_math():
    """複数のノイズが混在しても正しく処理される (旧挙動を明示指定)。"""
    text = (
        "段落1\n\n"
        "```\nThis block is not supported on your current device yet.\n```\n\n"
        "段落2 $$x = y$$ 続き。\n\n"
        "```\nThis block is not supported on your current device yet.\n```\n\n"
        "段落3\n"
    )
    cleaned, stats = clean_for_notion(text, convert_block_math=True)
    assert stats["unsupported_removed"] == 2
    assert stats["block_math_converted"] == 1
    assert cleaned.count("```") == 0  # 残らない


def test_fence_boundaries_repaired():
    """ノイズ除去後にフェンスの偶奇が整っていることを確認する。"""
    text = (
        "前\n\n```\nThis block is not supported on your current device yet.\n```\n\n"
        "中間\n\n```python\nx = 1\n```\n\n"
        "```\nThis block is not supported on your current device yet.\n```\n\n"
        "後\n"
    )
    cleaned, _ = clean_for_notion(text)
    assert cleaned.count("```") == 2  # 残るのは python ブロックのフェンスのみ


def test_options_can_disable_individual_steps():
    """個別オプションで処理を切り替えられる。"""
    text = "$$x = 1$$\n\n```\nThis block is not supported on your current device yet.\n```\n"

    # 0.5.5 既定 (convert_block_math=False) では $$ が保持される
    c0, s0 = clean_for_notion(text)
    assert "$$x = 1$$" in c0
    assert s0["block_math_converted"] == 0
    assert s0["unsupported_removed"] == 1

    # 数式変換のみ無効 (明示) + 非対応ブロック除去あり
    c1, s1 = clean_for_notion(text, convert_block_math=False)
    assert "$$x = 1$$" in c1
    assert s1["block_math_converted"] == 0
    assert s1["unsupported_removed"] == 1

    # 数式変換を明示的に有効化
    c2, s2 = clean_for_notion(text, convert_block_math=True)
    assert "$$" not in c2
    assert "`x = 1`" in c2

    # 非対応ブロック除去のみ無効
    c3, s3 = clean_for_notion(text, remove_unsupported=False)
    assert "This block is not supported" in c3
    assert s3["unsupported_removed"] == 0
    assert s2["block_math_converted"] == 1


# ========== conversation_to_notion_md との統合 ==========

def test_notion_md_default_applies_cleanup():
    """既定 (notion_safe=True) でクリーニングが適用される。"""
    completion = (
        "回答です。\n\n"
        "```\nThis block is not supported on your current device yet.\n```\n\n"
        "続きで数式: $$E = mc^2$$\n"
    )
    md = conversation_to_notion_md(_conv("pcp_001 質問", completion))
    # 0.5.5 では unsupported は除去されるが、$$...$$ は保持される
    assert "This block is not supported" not in md
    assert "$$E = mc^2$$" in md


def test_notion_md_can_disable_cleanup():
    """notion_safe=False で無加工 (デバッグ用)。"""
    completion = (
        "```\nThis block is not supported on your current device yet.\n```\n"
    )
    md = conversation_to_notion_md(
        _conv("pcp_001 質問", completion),
        notion_safe=False,
    )
    assert "This block is not supported" in md


def test_pcp_017_file_pattern_repaired():
    """pcp_017 で報告された実ファイル相当のパターンが修復される。"""
    completion = (
        "I'm recalling research on algebraic approaches.\n"
        "```\nThis block is not supported on your current device yet.\n```\n\n"
        "Now let me search for X.\n\n"
        "---\n"
        "```\nThis block is not supported on your current device yet.\n```\n\n"
        "Good, I have enough information.\n\n"
        "## 概要\n\n"
        "数式: $$a \\odot a = a$$\n"
    )
    md = conversation_to_notion_md(_conv("pcp_001 質問", completion))
    # フェンスは偶数 (整合性 OK)
    assert md.count("```") % 2 == 0
    # 非対応ブロックは消えている
    assert "This block is not supported" not in md
    # 0.5.5 では $$ は保持される (Notion がブロック数式として認識するため)
    assert "$$a \\odot a = a$$" in md
    # 本文の見出しは保持されている
    assert "## 概要" in md
