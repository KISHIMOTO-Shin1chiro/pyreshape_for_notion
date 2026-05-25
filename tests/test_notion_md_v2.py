"""
pcp_016 で報告された 3 つの不具合に対する回帰テスト。
  1. 見出し (##, ###) がプレーンテキスト化しない
  2. 本文の箇条書き階層が壊れない
  3. completion 本文の重複が除去される
"""

from pyreshape_for_notion.core.notion_md import (
    conversation_to_notion_md, shift_headings, dedupe_pcps, pair_into_pcps,
)
from pyreshape_for_notion.core.schema import make_conversation, make_message


def _conv(prompt, completion, name="T", extra_msgs=None):
    msgs = [
        make_message(uuid="m0", sender="human", text=prompt, index=0),
        make_message(uuid="m1", sender="assistant", text=completion, index=1),
    ]
    if extra_msgs:
        msgs.extend(extra_msgs)
    return make_conversation(uuid="u", name=name, messages=msgs)


def test_headings_not_indented():
    """本文中の見出しが 4 スペースインデントされない (プレーンテキスト化しない)。"""
    conv = _conv("pcp_001 q", "## 見出し\n\n本文")
    md = conversation_to_notion_md(conv)
    # 見出し行が行頭から始まる (インデントなし)
    assert "\n## 見出し" in md
    assert "    ## 見出し" not in md


def test_list_hierarchy_preserved():
    """箇条書きの 2 段階層が保持される。"""
    completion = "- A\n  - A1\n  - A2\n- B"
    conv = _conv("pcp_001 q", completion)
    md = conversation_to_notion_md(conv)
    assert "- A\n  - A1\n  - A2\n- B" in md


def test_code_block_not_extra_indented():
    """コードフェンスが余計にインデントされない。"""
    completion = "```python\nx = 1\n```"
    conv = _conv("pcp_001 q", completion)
    md = conversation_to_notion_md(conv)
    assert "\n```python\nx = 1\n```" in md


def test_pcp_is_heading():
    """pcp が H2 見出しになる。"""
    conv = _conv("pcp_001 q", "a")
    md = conversation_to_notion_md(conv)
    assert "## pcp_001" in md


def test_duplicate_pairs_removed():
    """同一 prompt-completion ペアの重複が除去される。"""
    extra = [
        make_message(uuid="m2", sender="human", text="pcp_001 q", index=2),
        make_message(uuid="m3", sender="assistant", text="a", index=3),
    ]
    conv = _conv("pcp_001 q", "a", extra_msgs=extra)
    md = conversation_to_notion_md(conv, dedupe=True)
    # 重複除去で pcp は 1 つだけ
    assert md.count("## pcp_") == 1


def test_dedupe_can_be_disabled():
    extra = [
        make_message(uuid="m2", sender="human", text="q2", index=2),
        make_message(uuid="m3", sender="assistant", text="a2", index=3),
    ]
    conv = _conv("q1", "a1", extra_msgs=extra)
    md = conversation_to_notion_md(conv, dedupe=False)
    assert md.count("## pcp_") == 2


def test_shift_headings_function():
    """見出しシフトの単体動作。"""
    # floor=2: H1→H2, H2→H3, H3→太字(上限超)
    assert shift_headings("# A", floor_level=2) == "## A"
    assert shift_headings("## B", floor_level=2) == "### B"
    assert shift_headings("### C", floor_level=2) == "**C**"


def test_shift_skips_code_fence():
    """コードフェンス内の # 行はシフトされない。"""
    text = "## 見出し\n```\n# コメント\n```"
    shifted = shift_headings(text, floor_level=2)
    assert "### 見出し" in shifted
    assert "# コメント" in shifted  # フェンス内は不変
