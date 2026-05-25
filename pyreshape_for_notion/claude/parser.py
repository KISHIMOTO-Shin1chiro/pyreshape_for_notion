"""
pyreshape_for_notion.claude.parser

Claude.ai 公式エクスポート (conversations.json, 単一ファイルに会話の配列)
をパースし、正規化済み会話 (NormalizedConv) を生成する。

Claude のエクスポートは既に uuid / name / chat_messages 構造を持つため、
本パーサは欠損フィールドの補完と index の正規化のみを行う。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.schema import NormalizedConv, make_conversation, make_message


def load_claude_export(path: Path) -> list[dict[str, Any]]:
    import json
    if not path.exists():
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(
            f"想定外のトップレベル型: {type(data).__name__}. "
            f"conversations.json は配列形式のはずです。"
        )
    return data


def _extract_text(msg: dict[str, Any]) -> str:
    """Claude メッセージから可視テキストを取り出す。"""
    if (msg.get("text") or "").strip():
        return msg["text"]
    content = msg.get("content")
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                t = c.get("text", "")
                if t:
                    parts.append(t)
        if parts:
            return "\n".join(parts)
    return msg.get("text") or ""


def normalize_conv(raw: dict[str, Any]) -> NormalizedConv:
    """Claude の生会話 dict を正規化会話に変換する。"""
    conv_id = raw.get("uuid") or raw.get("id") or ""
    name = raw.get("name") or ""
    created_at = raw.get("created_at") or ""
    updated_at = raw.get("updated_at") or ""

    raw_msgs = raw.get("chat_messages") or []
    # index 順にソート (index が無ければ元の順序)
    raw_msgs_sorted = sorted(
        enumerate(raw_msgs),
        key=lambda pair: pair[1].get("index", pair[0]),
    )

    messages = []
    for new_idx, (_, m) in enumerate(raw_msgs_sorted):
        sender = m.get("sender") or (
            "human" if m.get("raw_role") == "user" else "assistant")
        text = _extract_text(m)
        messages.append(make_message(
            uuid=m.get("uuid") or f"{conv_id}:{new_idx:04d}",
            sender=sender,
            text=text,
            index=new_idx,
            created_at=m.get("created_at") or created_at,
            updated_at=m.get("updated_at") or updated_at,
        ))

    return make_conversation(
        uuid=conv_id,
        name=name,
        messages=messages,
        created_at=created_at,
        updated_at=updated_at,
        source={"platform": "claude"},
    )


def parse_file(export_path: Path) -> list[NormalizedConv]:
    """conversations.json から正規化会話のリストを生成する。"""
    raw_list = load_claude_export(Path(export_path))
    return [normalize_conv(r) for r in raw_list]


def parse_folder(input_dir: Path) -> list[NormalizedConv]:
    """
    フォルダ内のすべての .json を読み、会話を結合して返す。
    (Claude は単一 conversations.json が標準だが、複数ファイルにも対応)
    """
    input_dir = Path(input_dir)
    if not input_dir.exists():
        raise FileNotFoundError(f"フォルダがありません: {input_dir}")
    convs: list[NormalizedConv] = []
    for p in sorted(input_dir.iterdir()):
        if p.suffix == ".json" and not p.name.startswith("_"):
            convs.extend(parse_file(p))
    return convs
