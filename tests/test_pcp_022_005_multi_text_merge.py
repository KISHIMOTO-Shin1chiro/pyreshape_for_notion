"""
pcp_022_005 で報告されたバグ (ChatGPT GPT-5 系で各 completion 冒頭が
切れる) に対する回帰テスト。

修正内容: ChatGPT パーサの normalize_conv 内で、human から次の human
までの区間にある「すべての assistant(text)」を 1 つの assistant
メッセージに連結する後処理を追加。

重要: この修正は ChatGPT パーサ内に完全に閉じており、Claude / Gemini
は一切影響を受けないことをテストで実証する。
"""

import json
from pathlib import Path

import pytest

from pyreshape_for_notion.chatgpt.parser import (
    normalize_conv,
    _merge_consecutive_assistant_texts,
)
from pyreshape_for_notion.core.notion_md import pair_into_pcps
from pyreshape_for_notion.core.schema import extract_visible_text


# ============================================================
# _merge_consecutive_assistant_texts 単体
# ============================================================
def _node(idx, sender, text, render_kind="text", create_time=None):
    return {
        "uuid": f"m{idx}",
        "sender": sender,
        "raw_role": sender,
        "render_kind": render_kind,
        "text": text,
        "extra": {},
        "created_at": "",
        "updated_at": "",
        "_create_time": float(idx) if create_time is None else create_time,
    }


def test_merge_three_assistant_texts_in_one_turn():
    """1 つの human ターン内の 3 つの assistant(text) が連結される。"""
    nodes = [
        _node(0, "human", "質問1"),
        _node(1, "assistant", "前置き", render_kind="text"),
        _node(2, "assistant", "search(...)", render_kind="code"),
        _node(3, "tool", "結果", render_kind="search_result"),
        _node(4, "assistant", "整理", render_kind="text"),
        _node(5, "assistant", "本論", render_kind="text"),
        _node(6, "human", "質問2"),
        _node(7, "assistant", "回答2", render_kind="text"),
    ]
    merged = _merge_consecutive_assistant_texts(nodes)

    # human 数は変わらず 2
    humans = [n for n in merged if n["sender"] == "human"]
    assert len(humans) == 2

    # assistant(text) は 3 個 → 1 個 (最初の human のターン) + 1 個 (2番目のターン) = 2 個
    ats = [n for n in merged
           if n["sender"] == "assistant" and n["render_kind"] == "text"]
    assert len(ats) == 2

    # 最初のターンの assistant(text) は連結内容
    assert ats[0]["text"] == "前置き\n\n整理\n\n本論"

    # 2 番目のターンは単一 (変化なし)
    assert ats[1]["text"] == "回答2"

    # assistant(code) と tool は保持される (本数変化なし)
    codes = [n for n in merged
             if n["sender"] == "assistant" and n["render_kind"] == "code"]
    assert len(codes) == 1
    tools = [n for n in merged if n["sender"] == "tool"]
    assert len(tools) == 1


def test_merge_single_assistant_text_unchanged():
    """1 ターンに assistant(text) が 1 つだけなら何も変化しない。"""
    nodes = [
        _node(0, "human", "q"),
        _node(1, "assistant", "回答", render_kind="text"),
        _node(2, "human", "q2"),
        _node(3, "assistant", "回答2", render_kind="text"),
    ]
    merged = _merge_consecutive_assistant_texts(nodes)
    assert len(merged) == 4
    assert merged[1]["text"] == "回答"
    assert merged[3]["text"] == "回答2"


def test_merge_empty_text_skipped():
    """空文字列の assistant(text) はマージ対象から除外される。"""
    nodes = [
        _node(0, "human", "q"),
        _node(1, "assistant", "", render_kind="text"),    # 空
        _node(2, "assistant", "本論", render_kind="text"),
        _node(3, "assistant", "  ", render_kind="text"),   # 空白のみ
        _node(4, "human", "q2"),
    ]
    merged = _merge_consecutive_assistant_texts(nodes)
    ats = [n for n in merged
           if n["sender"] == "assistant" and n["render_kind"] == "text"]
    # 連結対象は "本論" 1 個だけなので何も変化しない (len(at_indices) <= 1)
    assert len(ats) == 3  # 空も含めて 3 個そのまま残る
    # ただし非空は "本論" のみ
    non_empty = [n for n in ats if (n["text"] or "").strip()]
    assert len(non_empty) == 1
    assert non_empty[0]["text"] == "本論"


def test_merge_no_human_returns_unchanged():
    """human がない場合は何もしない。"""
    nodes = [
        _node(0, "assistant", "a1", render_kind="text"),
        _node(1, "assistant", "a2", render_kind="text"),
    ]
    merged = _merge_consecutive_assistant_texts(nodes)
    assert merged == nodes


def test_merge_preserves_order_and_uuid_of_first():
    """連結結果は「最初の assistant(text) の位置」に置かれ、uuid もそれを引き継ぐ。"""
    nodes = [
        _node(0, "human", "q"),
        _node(1, "assistant", "A", render_kind="text"),  # uuid="m1"
        _node(2, "assistant", "B", render_kind="text"),  # uuid="m2"
        _node(3, "assistant", "C", render_kind="text"),  # uuid="m3"
    ]
    merged = _merge_consecutive_assistant_texts(nodes)
    ats = [n for n in merged
           if n["sender"] == "assistant" and n["render_kind"] == "text"]
    assert len(ats) == 1
    assert ats[0]["uuid"] == "m1"
    assert ats[0]["text"] == "A\n\nB\n\nC"


# ============================================================
# 実 GPT-5.5 Pro エクスポートでの検証
# ============================================================
def test_real_gpt5_export_pcp_022_005():
    """実際の GPT-5.5 Pro エクスポートで本論が含まれることを確認。"""
    src = Path("/mnt/user-data/uploads/conversations-021.json")
    if not src.exists():
        pytest.skip("テスト用エクスポートが存在しない")

    data = json.load(open(src, encoding="utf-8-sig"))
    target = next((c for c in data
                   if c.get("id", "").startswith("6a0d1240")), None)
    if target is None:
        pytest.skip("対象会話が見つからない")

    norm = normalize_conv(target)
    msgs = norm["chat_messages"]
    pcps = pair_into_pcps(msgs)

    # 10 個の pcp があり、すべて assistant が None でないこと
    assert len(pcps) == 10
    for i, (h, a) in enumerate(pcps):
        assert a is not None, f"pair[{i}] の assistant が None"
        comp_text = extract_visible_text(a)
        # 各 completion が「前置きだけ」(数百文字以下) でなく、十分長いこと
        # GPT-5.5 Pro の本論は通常 5000 文字以上
        assert len(comp_text) > 3000, (
            f"pair[{i}] の completion が短すぎる: {len(comp_text)} 文字"
        )


# ============================================================
# 他プラットフォーム (Claude/Gemini) への影響を排除
# ============================================================
def test_claude_parser_not_affected():
    """Claude のパーサ動作が影響を受けないことを確認。"""
    from pyreshape_for_notion.claude.parser import normalize_conv as norm_claude

    raw = {
        "uuid": "c1",
        "name": "T",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "chat_messages": [
            {"uuid": "m0", "sender": "human", "index": 0, "text": "q1"},
            {"uuid": "m1", "sender": "assistant", "index": 1, "text": "a1"},
            {"uuid": "m2", "sender": "human", "index": 2, "text": "q2"},
            {"uuid": "m3", "sender": "assistant", "index": 3, "text": "a2"},
        ],
    }
    conv = norm_claude(raw)
    msgs = conv["chat_messages"]
    # Claude は assistant が 1 ターン 1 メッセージ。マージ処理は呼ばれない。
    assert len(msgs) == 4
    pcps = pair_into_pcps(msgs)
    assert len(pcps) == 2
    assert extract_visible_text(pcps[0][1]) == "a1"
    assert extract_visible_text(pcps[1][1]) == "a2"


def test_gemini_parser_not_affected(tmp_path):
    """Gemini のパーサ動作が影響を受けないことを確認。"""
    from pyreshape_for_notion.gemini.parser import parse_file

    md = (
        "# Gemini Chat Export\n\n"
        "> Exported on: 2026/5/13 15:00\n\n"
        "---\n\n"
        "## 👤 You\n\npcp_001 質問1\n\n"
        "## 🤖 Gemini\n\n回答1\n\n"
        "---\n\n"
        "## 👤 You\n\npcp_002 質問2\n\n"
        "## 🤖 Gemini\n\n回答2\n\n"
        "---\n"
    )
    f = tmp_path / "2025-12-19_test.md"
    f.write_text(md, encoding="utf-8")

    conv = parse_file(f)
    msgs = conv["chat_messages"]
    # Gemini は 2 ターン = 2 human + 2 assistant = 4 messages
    assert len(msgs) == 4
    pcps = pair_into_pcps(msgs)
    assert len(pcps) == 2
