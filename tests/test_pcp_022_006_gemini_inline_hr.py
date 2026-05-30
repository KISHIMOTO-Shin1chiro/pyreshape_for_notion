"""
pcp_022_006 で報告されたバグ (Gemini で本文中の --- を会話区切りと誤認し、
回答が分割・重複していた) に対する回帰テスト。

修正内容: Gemini パーサで `---` (水平線) を検出した際、次に出現する非空行が
`## 👤 You` または `## 🤖 Gemini` の場合のみ会話区切りとして扱い、
それ以外は本文中の水平線として保持するように変更。

重要: この修正は Gemini パーサ内 (gemini/parser.py) のみで完結し、
ChatGPT / Claude には一切影響しない。
"""

from pathlib import Path

import pytest

from pyreshape_for_notion.gemini.parser import parse_gemini_md, parse_file
from pyreshape_for_notion.core.notion_md import pair_into_pcps
from pyreshape_for_notion.core.schema import extract_visible_text


# ============================================================
# parse_gemini_md: 本文中の --- の取扱い
# ============================================================
def test_in_body_hr_not_treated_as_conversation_separator():
    """本文中の --- (次が会話マーカーでない) は本文として保持される。"""
    md = (
        "# Gemini Chat Export\n\n"
        "> Exported on: 2026/5/13 10:00\n\n"
        "---\n\n"
        "## 👤 You\n\n"
        "pcp_001 質問\n\n"
        "## 🤖 Gemini\n\n"
        "導入の段落\n\n"
        "---\n\n"
        "### 検証セクション\n\n"
        "本論の段落\n\n"
        "---\n\n"
        "### 結論\n\n"
        "結論の段落\n\n"
        "---\n\n"
        "## 👤 You\n\n"
        "pcp_002 次の質問\n\n"
        "## 🤖 Gemini\n\n"
        "次の回答\n\n"
        "---\n"
    )
    result = parse_gemini_md(md)
    msgs = result["messages"]

    # human 2, assistant 2 で合計 4 メッセージのはず
    humans = [m for m in msgs if m["sender"] == "human"]
    assistants = [m for m in msgs if m["sender"] == "assistant"]
    assert len(humans) == 2
    assert len(assistants) == 2

    # 最初の assistant 回答が「導入 + 本論 + 結論」を全て含む
    a1 = assistants[0]["text"]
    assert "導入の段落" in a1
    assert "### 検証セクション" in a1
    assert "本論の段落" in a1
    assert "### 結論" in a1
    assert "結論の段落" in a1

    # 本文中の --- も保持されている (構造区切り)
    assert a1.count("---") == 2


def test_regular_conversation_separator_still_works():
    """会話区切りとしての --- は従来通り flush として動作する。"""
    md = (
        "# Gemini Chat Export\n\n"
        "> Exported on: 2026/5/13 10:00\n\n"
        "---\n\n"
        "## 👤 You\n\n"
        "質問1\n\n"
        "## 🤖 Gemini\n\n"
        "回答1\n\n"
        "---\n\n"
        "## 👤 You\n\n"
        "質問2\n\n"
        "## 🤖 Gemini\n\n"
        "回答2\n\n"
        "---\n"
    )
    result = parse_gemini_md(md)
    msgs = result["messages"]
    assert len(msgs) == 4
    assert msgs[0]["sender"] == "human" and msgs[0]["text"] == "質問1"
    assert msgs[1]["sender"] == "assistant" and msgs[1]["text"] == "回答1"
    assert msgs[2]["sender"] == "human" and msgs[2]["text"] == "質問2"
    assert msgs[3]["sender"] == "assistant" and msgs[3]["text"] == "回答2"


def test_hr_followed_by_blank_lines_then_marker_is_separator():
    """--- の後に空行を挟んでマーカーが来るのは会話区切り。"""
    md = (
        "# Gemini Chat Export\n\n"
        "> Exported on: 2026/5/13 10:00\n\n"
        "---\n\n"
        "## 👤 You\n\nq1\n\n"
        "## 🤖 Gemini\n\na1\n\n"
        "---\n"
        "\n"
        "\n"
        "## 👤 You\n\nq2\n\n"
        "## 🤖 Gemini\n\na2\n\n"
        "---\n"
    )
    result = parse_gemini_md(md)
    msgs = result["messages"]
    assert len(msgs) == 4


def test_real_gemini_export_pcp_022_006():
    """実際の Gemini エクスポートで pair[1] が本論を含むことを確認。"""
    src = Path("/mnt/user-data/uploads/Completed_2026-01-09_Mathematical_Proofs_and_Commutative_Diagrams_in_Belief-Function_Epistemology_--_Part_1.md")
    if not src.exists():
        pytest.skip("テスト用エクスポートが存在しない")

    conv = parse_file(src)
    pcps = pair_into_pcps(conv["chat_messages"])

    # 149 ペア (生エクスポートの ## 👤 You と同数)
    assert len(pcps) == 149

    # pair[1] (pcp_001) の assistant が本論を含むことを確認
    a1 = extract_visible_text(pcps[1][1])
    # 修正前は 405 文字 (導入のみ)、修正後は 2400 文字超 (本論含む)
    assert len(a1) > 2000, f"pcp_001 の assistant が短すぎる: {len(a1)} 文字"
    # 本論の核心的キーワードが含まれていること
    assert "Step 1" in a1 or "第一段階" in a1
    assert "Step 2" in a1 or "第二段階" in a1
    assert "結論" in a1


# ============================================================
# 他プラットフォーム (ChatGPT/Claude) への影響を排除
# ============================================================
def test_chatgpt_parser_not_affected():
    """ChatGPT パーサに変更が及んでいないことを確認。"""
    from pyreshape_for_notion.chatgpt.parser import normalize_conv

    raw = {
        "id": "test-conv",
        "title": "T",
        "create_time": 1700000000.0,
        "update_time": 1700000000.0,
        "mapping": {
            "n1": {"id": "n1", "parent": None, "children": ["n2"],
                   "message": {"id": "n1", "author": {"role": "user"},
                               "create_time": 1700000000.0,
                               "content": {"content_type": "text", "parts": ["q"]},
                               "metadata": {}}},
            "n2": {"id": "n2", "parent": "n1", "children": [],
                   "message": {"id": "n2", "author": {"role": "assistant"},
                               "create_time": 1700000060.0,
                               "content": {"content_type": "text", "parts": ["a"]},
                               "metadata": {}}},
        },
    }
    conv = normalize_conv(raw)
    msgs = conv["chat_messages"]
    assert len(msgs) == 2
    pcps = pair_into_pcps(msgs)
    assert len(pcps) == 1
    assert extract_visible_text(pcps[0][1]) == "a"


def test_claude_parser_not_affected():
    """Claude パーサに変更が及んでいないことを確認。"""
    from pyreshape_for_notion.claude.parser import normalize_conv

    raw = {
        "uuid": "c1", "name": "T",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "chat_messages": [
            {"uuid": "m0", "sender": "human", "index": 0, "text": "q1"},
            {"uuid": "m1", "sender": "assistant", "index": 1, "text": "a1\n\n---\n\n本文中の水平線"},
        ],
    }
    conv = normalize_conv(raw)
    msgs = conv["chat_messages"]
    assert len(msgs) == 2
    # Claude では本文中の --- もそのまま保持される (Claude パーサは splitter として
    # --- を使わないので何も変わらない)
    assert "---" in msgs[1]["text"]
    assert "本文中の水平線" in msgs[1]["text"]
