"""
pcp_022_010 で報告されたバグ (ChatGPT 由来 md で文中の引用と引用文献リストが
すべて文字化けていた) に対する回帰テスト。

修正内容: ChatGPT パーサで、本文中の PUA 文字 (\\ue200-\\ue202) を含む引用
マーカー (cite, filecite 等) を除去し、metadata.content_references の
全 URL を「## このターンの参考文献」として本文末尾に列挙する。

重要: この修正は ChatGPT パーサ (chatgpt/parser.py) 内のみで完結し、
Claude / Gemini には一切影響しない。
"""

import json
from pathlib import Path

import pytest

from pyreshape_for_notion.chatgpt.parser import (
    _process_citation_markers,
    normalize_conv,
)
from pyreshape_for_notion.core.notion_md import pair_into_pcps
from pyreshape_for_notion.core.schema import extract_visible_text


# ============================================================
# _process_citation_markers の単体テスト
# ============================================================
def test_strip_pua_cite_marker():
    """通常の cite マーカー (PUA 文字で囲まれた) が除去される。"""
    text = "前置き\ue200cite\ue202turn792083view0\ue201続きの段落"
    result = _process_citation_markers(text, None)
    assert "\ue200" not in result
    assert "\ue201" not in result
    assert "\ue202" not in result
    assert "cite" not in result
    assert "turn792083" not in result
    assert "前置き続きの段落" == result


def test_strip_filecite_marker():
    """filecite マーカー (添付ファイル引用) も除去される。"""
    text = "本文\ue200filecite\ue202turn1file3\ue201さらに本文"
    result = _process_citation_markers(text, None)
    assert "\ue200" not in result
    assert "filecite" not in result
    assert "turn1file3" not in result
    assert "本文さらに本文" == result


def test_strip_orphan_pua_chars():
    """裸の PUA 文字 (対応のないもの) も除去される。"""
    text = "前\ue200後\ue202\ue201残骸"
    result = _process_citation_markers(text, None)
    assert all(ord(c) < 0xE000 or ord(c) > 0xE202 for c in result)


def test_text_without_markers_returns_appended_refs():
    """マーカーが無くても content_references があれば末尾に追加される。"""
    text = "本文のみ"
    refs = [{"items": [
        {"url": "https://example.com/a", "title": "Example A", "attribution": "Example"},
    ]}]
    result = _process_citation_markers(text, refs)
    assert "本文のみ" in result
    assert "## このターンの参考文献" in result
    assert "https://example.com/a" in result
    assert "Example A" in result


def test_appends_reference_section():
    """参考文献セクションが本文末尾に正しく追加される。"""
    text = "回答本文\ue200cite\ue202turn1view0\ue201です。"
    refs = [
        {"items": [
            {"url": "https://example.com/foo", "title": "Foo", "attribution": "Example"},
        ]},
        {"items": [
            {"url": "https://example.com/bar", "title": "Bar", "attribution": "Other"},
        ]},
    ]
    result = _process_citation_markers(text, refs)
    assert "回答本文です。" in result
    assert "## このターンの参考文献" in result
    assert "1. [Foo](https://example.com/foo) (Example)" in result
    assert "2. [Bar](https://example.com/bar) (Other)" in result


def test_dedupe_urls():
    """同じ URL は 1 つにまとめられる。"""
    text = "本文"
    refs = [
        {"items": [{"url": "https://x.com/a", "title": "A", "attribution": "x"}]},
        {"items": [{"url": "https://x.com/a", "title": "A", "attribution": "x"}]},
        {"items": [{"url": "https://x.com/b", "title": "B", "attribution": "x"}]},
    ]
    result = _process_citation_markers(text, refs)
    assert result.count("https://x.com/a") == 1
    assert result.count("https://x.com/b") == 1


def test_no_references_no_section():
    """content_references が無く、マーカーも無ければ本文そのまま。"""
    text = "通常の本文"
    result = _process_citation_markers(text, None)
    assert result == "通常の本文"


def test_empty_content_references_no_section():
    """content_references が空リストなら参考文献セクションは付かない。"""
    text = "本文\ue200cite\ue202turn1view0\ue201です。"
    result = _process_citation_markers(text, [])
    assert "本文です。" in result
    assert "## このターンの参考文献" not in result


# ============================================================
# 実エクスポートでの統合テスト
# ============================================================
def test_real_gpt5_export_pcp_022_010():
    """実エクスポート (conversations-021.json, 6a17defc 会話) で
    文字化けが解消され、参考文献セクションが付加されることを確認。"""
    src = Path("/mnt/user-data/uploads/conversations-021.json")
    if not src.exists():
        pytest.skip("テスト用エクスポートが存在しない")

    data = json.load(open(src, encoding="utf-8-sig"))
    target = next((c for c in data
                   if c.get("id", "").startswith("6a17defc")), None)
    if target is None:
        pytest.skip("対象会話が見つからない")

    conv = normalize_conv(target)
    msgs = conv["chat_messages"]
    all_text = "\n".join(m.get("text", "") for m in msgs)

    # PUA 文字が完全に除去されている
    pua_count = sum(1 for c in all_text if 0xE000 <= ord(c) <= 0xF8FF)
    assert pua_count == 0, f"PUA 文字が {pua_count} 個残存"

    # citeturn のような文字列も残らない
    import re
    cite_residue = re.findall(r'\w*cite\w*turn\w+', all_text)
    assert len(cite_residue) == 0, f"cite 残存: {cite_residue[:5]}"

    # 参考文献セクションが付加されている (引用が含まれる pcp に)
    assert "## このターンの参考文献" in all_text


# ============================================================
# 他プラットフォームへの非影響
# ============================================================
def test_claude_unaffected():
    """Claude パーサが今回の修正の影響を受けないことを確認。"""
    from pyreshape_for_notion.claude.parser import normalize_conv as claude_norm
    raw = {
        "uuid": "c1", "name": "T",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "chat_messages": [
            {"uuid": "m0", "sender": "human", "index": 0, "text": "q"},
            {"uuid": "m1", "sender": "assistant", "index": 1, "text": "a"},
        ],
    }
    conv = claude_norm(raw)
    msgs = conv["chat_messages"]
    # 内容に「## このターンの参考文献」が混入していない
    for m in msgs:
        assert "## このターンの参考文献" not in (m.get("text") or "")


def test_gemini_unaffected(tmp_path):
    """Gemini パーサが今回の修正の影響を受けないことを確認。"""
    from pyreshape_for_notion.gemini.parser import parse_file
    md = (
        "# Gemini Chat Export\n\n"
        "> Exported on: 2026/5/13 10:00\n\n"
        "---\n\n"
        "## 👤 You\n\nq\n\n"
        "## 🤖 Gemini\n\na\n\n"
        "---\n"
    )
    f = tmp_path / "2025-12-19_test.md"
    f.write_text(md, encoding="utf-8")
    conv = parse_file(f)
    for m in conv["chat_messages"]:
        assert "## このターンの参考文献" not in (m.get("text") or "")


def test_display_text_fallback_when_title_is_url():
    """title が URL 文字列 (取得失敗時) のとき、attribution を表示テキストに使う。"""
    from pyreshape_for_notion.chatgpt.parser import _process_citation_markers

    text = "本文"
    refs = [{
        "items": [{
            "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9039193/",
            "title": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9039193/",  # title が URL
            "attribution": "PMC",
            "refs": [{"turn_index": 1, "ref_type": "search", "ref_index": 0}],
        }]
    }]
    out = _process_citation_markers(text, refs)
    # title 部分が URL ではなく PMC になっているか
    assert "1. [PMC](" in out
    assert "[https://" not in out.split("## このターンの参考文献")[1]


def test_display_text_fallback_when_title_and_attribution_both_empty():
    """title も attribution も無いとき、URL のホスト名を表示に使う。"""
    from pyreshape_for_notion.chatgpt.parser import _process_citation_markers

    text = "本文"
    refs = [{
        "items": [{
            "url": "https://example.com/path/to/page",
            "title": "",
            "attribution": "",
            "refs": [{"turn_index": 1, "ref_type": "search", "ref_index": 0}],
        }]
    }]
    out = _process_citation_markers(text, refs)
    # ホスト名が使われる
    assert "1. [example.com](https://example.com/path/to/page)" in out


def test_display_text_uses_normal_title_when_present():
    """title が通常文字列のときは title を使う。"""
    from pyreshape_for_notion.chatgpt.parser import _process_citation_markers

    text = "本文"
    refs = [{
        "items": [{
            "url": "https://example.com/article",
            "title": "Normal Article Title",
            "attribution": "Example Site",
            "refs": [{"turn_index": 1, "ref_type": "search", "ref_index": 0}],
        }]
    }]
    out = _process_citation_markers(text, refs)
    assert "1. [Normal Article Title](https://example.com/article) (Example Site)" in out
