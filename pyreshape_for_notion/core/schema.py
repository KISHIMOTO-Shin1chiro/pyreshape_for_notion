"""
pyreshape_for_notion.core.schema

3 プラットフォーム共通の「正規化済み会話」のスキーマ定義と補助関数。

正規化済み会話 (NormalizedConv) は、ChatGPT / Claude / Gemini の各
パーサが共通して出力する dict 形式で、以降の core 層の処理 (Notion MD 化、
差分検出、pcp 分割など) はすべてこの形式を入力とする。

スキーマ:
  {
    "uuid": str,                       # 会話の一意 ID
    "name": str,                       # 会話タイトル
    "chat_messages": [
      {
        "uuid": str,
        "sender": "human" | "assistant",
        "raw_role": str,
        "render_kind": "text",
        "text": str,
        "content": [{"type": "text", "text": str}],
        "extra": dict,
        "created_at": str,             # ISO 8601
        "updated_at": str,             # ISO 8601
        "index": int,
      },
      ...
    ],
    "created_at": str,                 # ISO 8601
    "updated_at": str,                 # ISO 8601
    "_source": {
      "platform": "chatgpt" | "claude" | "gemini",
      ...                              # プラットフォーム固有メタデータ
    }
  }
"""

from __future__ import annotations

from typing import Any, TypedDict


class NormalizedMessage(TypedDict, total=False):
    uuid: str
    sender: str          # "human" | "assistant"
    raw_role: str
    render_kind: str
    text: str
    content: list[dict[str, Any]]
    extra: dict[str, Any]
    created_at: str
    updated_at: str
    index: int


class NormalizedConv(TypedDict, total=False):
    uuid: str
    name: str
    chat_messages: list[NormalizedMessage]
    created_at: str
    updated_at: str
    _source: dict[str, Any]


def make_message(
    *,
    uuid: str,
    sender: str,
    text: str,
    index: int,
    created_at: str = "",
    updated_at: str = "",
    raw_role: str | None = None,
    render_kind: str = "text",
    extra: dict[str, Any] | None = None,
) -> NormalizedMessage:
    """正規化メッセージを 1 件構築する補助関数。"""
    if raw_role is None:
        raw_role = "user" if sender == "human" else "assistant"
    return {
        "uuid": uuid,
        "sender": sender,
        "raw_role": raw_role,
        "render_kind": render_kind,
        "text": text,
        "content": [{"type": "text", "text": text}],
        "extra": extra or {},
        "created_at": created_at,
        "updated_at": updated_at,
        "index": index,
    }


def make_conversation(
    *,
    uuid: str,
    name: str,
    messages: list[NormalizedMessage],
    created_at: str = "",
    updated_at: str = "",
    source: dict[str, Any] | None = None,
) -> NormalizedConv:
    """正規化会話を 1 件構築する補助関数。"""
    return {
        "uuid": uuid,
        "name": name,
        "chat_messages": messages,
        "created_at": created_at,
        "updated_at": updated_at,
        "_source": source or {},
    }


def extract_visible_text(msg: NormalizedMessage) -> str:
    """メッセージの可視テキストを取り出す。content を優先し、無ければ text。"""
    content = msg.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text", "")
                if t:
                    parts.append(t)
        if parts:
            return "\n".join(parts)
    return msg.get("text") or ""


def is_message_empty(msg: NormalizedMessage) -> bool:
    """メッセージが空 (本文が無い) か判定する。"""
    if (msg.get("text") or "").strip():
        return False
    content = msg.get("content")
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                if (c.get("text") or "").strip():
                    return False
    return True


def is_empty_chat(
    conv: NormalizedConv,
    threshold: float = 0.95,
) -> tuple[bool, dict[str, Any]]:
    """
    会話が「空会話」 (削除済み等で本文がほぼ欠落) か判定する。

    返り値: (is_empty, stats)
      stats = {"n_messages": int, "n_empty": int, "empty_ratio": float}
    """
    msgs = conv.get("chat_messages") or []
    n_total = len(msgs)
    if n_total == 0:
        return True, {"n_messages": 0, "n_empty": 0, "empty_ratio": 1.0}
    n_empty = sum(1 for m in msgs if is_message_empty(m))
    ratio = n_empty / n_total
    return ratio >= threshold, {
        "n_messages": n_total,
        "n_empty": n_empty,
        "empty_ratio": ratio,
    }
