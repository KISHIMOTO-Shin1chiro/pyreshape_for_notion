"""
pcp_022 で報告されたバグ (拡張推論やツール使用が入ると以降が切れる) に
対する回帰テスト。

原因: pair_into_pcps が「human の次の assistant」を無条件で pair の相手に
していたため、ChatGPT のツール使用パターン
    human → assistant(code: search) → tool(検索結果) → assistant(text: 最終回答)
において、最初の assistant(code) がペアの相手になり、本来の最終回答が
捨てられていた。

修正: render_kind == "text" の assistant メッセージのみを pair の相手とし、
code / tool / その他の中間メッセージはスキップする。
"""

from pyreshape_for_notion.core.notion_md import pair_into_pcps
from pyreshape_for_notion.core.schema import (
    make_conversation, make_message, extract_visible_text,
)
from pyreshape_for_notion.core.notion_md import conversation_to_notion_md


def _msg(idx, sender, text, render_kind="text"):
    """テスト用メッセージ作成 (render_kind を明示)。"""
    return make_message(
        uuid=f"m{idx}", sender=sender, text=text, index=idx,
        render_kind=render_kind,
    )


def test_pair_skips_assistant_code_keeps_final_text():
    """assistant(code) はスキップされ、後続の assistant(text) が pair の相手になる。"""
    msgs = [
        _msg(0, "human", "pcp_001 質問"),
        _msg(1, "assistant", "search('foo')", render_kind="code"),
        _msg(2, "assistant", "最終回答です", render_kind="text"),
    ]
    pcps = pair_into_pcps(msgs)
    assert len(pcps) == 1
    human, assistant = pcps[0]
    assert extract_visible_text(human) == "pcp_001 質問"
    assert extract_visible_text(assistant) == "最終回答です"


def test_pair_skips_tool_messages():
    """sender='tool' のメッセージは無視される。"""
    msgs = [
        _msg(0, "human", "pcp_001 質問"),
        _msg(1, "assistant", "search('foo')", render_kind="code"),
        _msg(2, "tool", "検索結果1", render_kind="search_result"),
        _msg(3, "tool", "検索結果2", render_kind="search_result"),
        _msg(4, "assistant", "結果に基づく最終回答", render_kind="text"),
    ]
    pcps = pair_into_pcps(msgs)
    assert len(pcps) == 1
    assert extract_visible_text(pcps[0][1]) == "結果に基づく最終回答"


def test_pair_handles_multiple_search_iterations():
    """複数回のツール使用 (search → click → search → ...) でも最終 text を拾う。"""
    msgs = [
        _msg(0, "human", "pcp_001 質問"),
        _msg(1, "assistant", "search('a')", render_kind="code"),
        _msg(2, "tool", "結果A", render_kind="search_result"),
        _msg(3, "assistant", "mclick([0])", render_kind="code"),
        _msg(4, "tool", "詳細A", render_kind="search_result"),
        _msg(5, "assistant", "search('b')", render_kind="code"),
        _msg(6, "tool", "結果B", render_kind="search_result"),
        _msg(7, "assistant", "総合的な最終回答", render_kind="text"),
    ]
    pcps = pair_into_pcps(msgs)
    assert len(pcps) == 1
    assert extract_visible_text(pcps[0][1]) == "総合的な最終回答"


def test_pair_orphan_human_keeps_none():
    """人間の再質問で最終回答が無い場合は assistant=None になる。"""
    msgs = [
        _msg(0, "human", "pcp_001 質問A"),
        _msg(1, "assistant", "search('foo')", render_kind="code"),
        # ここで最終 text が無いまま次の human が来る
        _msg(2, "human", "pcp_002 別の質問"),
        _msg(3, "assistant", "回答B", render_kind="text"),
    ]
    pcps = pair_into_pcps(msgs)
    assert len(pcps) == 2
    # 最初の human はペアなし
    assert pcps[0][1] is None
    assert extract_visible_text(pcps[0][0]) == "pcp_001 質問A"
    # 2 番目の human は正しく pair
    assert extract_visible_text(pcps[1][1]) == "回答B"


def test_pair_multiple_pcps_with_tool_use():
    """複数 pcp にまたがるツール使用パターン (実 ChatGPT エクスポート相当)。"""
    msgs = [
        # pcp_001: 普通
        _msg(0, "human", "pcp_001 普通の質問"),
        _msg(1, "assistant", "普通の回答", render_kind="text"),
        # pcp_002: ツール使用あり
        _msg(2, "human", "pcp_002 調査質問"),
        _msg(3, "assistant", "search('x')", render_kind="code"),
        _msg(4, "tool", "結果", render_kind="search_result"),
        _msg(5, "assistant", "調査の結果", render_kind="text"),
        # pcp_003: 普通
        _msg(6, "human", "pcp_003 続けて"),
        _msg(7, "assistant", "続きの回答", render_kind="text"),
    ]
    pcps = pair_into_pcps(msgs)
    assert len(pcps) == 3
    assert extract_visible_text(pcps[0][1]) == "普通の回答"
    assert extract_visible_text(pcps[1][1]) == "調査の結果"
    assert extract_visible_text(pcps[2][1]) == "続きの回答"


def test_claude_normal_behavior_unchanged():
    """Claude/Gemini の通常パターン (render_kind=text のみ) は影響を受けない。"""
    msgs = [
        _msg(0, "human", "q1"),
        _msg(1, "assistant", "a1"),
        _msg(2, "human", "q2"),
        _msg(3, "assistant", "a2"),
    ]
    pcps = pair_into_pcps(msgs)
    assert len(pcps) == 2
    assert extract_visible_text(pcps[0][1]) == "a1"
    assert extract_visible_text(pcps[1][1]) == "a2"


def test_full_md_output_excludes_search_noise():
    """Notion MD 出力にも反映され、search 呼び出しコードが本文に出ない。"""
    conv = make_conversation(
        uuid="t", name="ツール使用会話",
        messages=[
            _msg(0, "human", "pcp_001 化学メーカーのLLM利用例"),
            _msg(1, "assistant", "search('LLM chemistry')", render_kind="code"),
            _msg(2, "tool", "検索結果...", render_kind="search_result"),
            _msg(3, "assistant", "化学メーカーは...という事例があります", render_kind="text"),
        ],
    )
    md = conversation_to_notion_md(conv)
    # 本文には最終回答だけが含まれ、search 呼び出しコードは含まれない
    assert "化学メーカーは...という事例があります" in md
    assert "search('LLM chemistry')" not in md
    assert "検索結果" not in md
