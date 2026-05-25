"""
pyreshape_for_notion.chatgpt.parser

ChatGPT 公式エクスポート (conversations-*.json, 各ファイルに会話の配列)
をパースし、正規化済み会話 (NormalizedConv) を生成する。

ChatGPT は mapping (ノードの木構造) を持つため、これを線形メッセージ列に
変換する正規化が必要。旧 Code_001 (chatgpt) のロジックを移植。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.schema import NormalizedConv, make_conversation, make_message


def _ts_to_iso(ts: Any) -> str:
    if not isinstance(ts, (int, float)):
        return ""
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        return ""


def _extract_text_from_parts(parts: list[Any]) -> tuple[str, list[str]]:
    text_parts: list[str] = []
    image_refs: list[str] = []
    for p in parts or []:
        if isinstance(p, str):
            if p:
                text_parts.append(p)
        elif isinstance(p, dict):
            ct = p.get("content_type")
            if ct == "image_asset_pointer":
                ap = p.get("asset_pointer", "") or ""
                if ap:
                    image_refs.append(ap)
                    text_parts.append(f"[image: {ap}]")
            else:
                t = p.get("text") or ""
                if t:
                    text_parts.append(t)
    return "\n".join(text_parts), image_refs


def _classify_message(msg: dict[str, Any]) -> dict[str, Any] | None:
    author = msg.get("author") or {}
    role = author.get("role") or ""
    name = author.get("name") or ""
    content = msg.get("content") or {}
    ctype = content.get("content_type")
    metadata = msg.get("metadata") or {}

    if role == "system":
        if not metadata.get("is_user_system_message"):
            return None
        if ctype == "text":
            text, _ = _extract_text_from_parts(content.get("parts") or [])
        else:
            return None
        if not text.strip():
            return None
        return {"role": "system", "render_kind": "system_instruction",
                "text": text, "extra": {"author_name": name}}

    if role not in ("user", "assistant", "tool"):
        return None

    extra: dict[str, Any] = {}
    if name:
        extra["author_name"] = name
    text = ""
    render_kind = "text"

    if ctype == "text":
        text, image_refs = _extract_text_from_parts(content.get("parts") or [])
        if image_refs:
            extra["image_refs"] = image_refs
    elif ctype == "multimodal_text":
        text, image_refs = _extract_text_from_parts(content.get("parts") or [])
        if image_refs:
            render_kind = "image_ref"
            extra["image_refs"] = image_refs
    elif ctype == "code":
        text = content.get("text") or ""
        render_kind = "code"
        lang = content.get("language")
        if lang:
            extra["language"] = lang
    elif ctype == "execution_output":
        text = content.get("text") or ""
        render_kind = "exec_output"
    elif ctype == "tether_quote":
        text = content.get("text") or ""
        render_kind = "search_result"
        domain = content.get("domain")
        if domain:
            extra["source_domain"] = domain
    elif ctype == "tether_browsing_display":
        text = content.get("result") or ""
        render_kind = "search_result"
    elif ctype == "system_error":
        text = content.get("text") or content.get("name") or ""
        render_kind = "system_error"
    else:
        return None

    if not text.strip():
        return None
    return {"role": role, "render_kind": render_kind,
            "text": text, "extra": extra}


def normalize_conv(raw: dict[str, Any]) -> NormalizedConv:
    """ChatGPT の生会話 dict (mapping 構造) を正規化会話に変換する。"""
    mapping = raw.get("mapping") or {}
    nodes: list[dict[str, Any]] = []

    for node_id, node in mapping.items():
        if not isinstance(node, dict):
            continue
        msg = node.get("message")
        if not isinstance(msg, dict):
            continue
        classified = _classify_message(msg)
        if classified is None:
            continue

        role = classified["role"]
        if role == "user":
            sender = "human"
        elif role == "assistant":
            sender = "assistant"
        elif role == "tool":
            sender = "tool"
        else:
            sender = "system"

        ts = msg.get("create_time")
        nodes.append({
            "uuid": msg.get("id") or node_id,
            "sender": sender,
            "raw_role": role,
            "render_kind": classified["render_kind"],
            "text": classified["text"],
            "extra": classified["extra"],
            "created_at": _ts_to_iso(ts),
            "updated_at": _ts_to_iso(msg.get("update_time") or ts),
            "_create_time": ts if isinstance(ts, (int, float)) else 0.0,
        })

    nodes.sort(key=lambda n: n["_create_time"])

    conv_id = raw.get("id") or raw.get("conversation_id") or ""
    name = raw.get("title") or ""
    created_at = _ts_to_iso(raw.get("create_time"))
    updated_at = _ts_to_iso(raw.get("update_time"))

    messages = []
    for i, n in enumerate(nodes):
        messages.append(make_message(
            uuid=n["uuid"],
            sender=n["sender"],
            text=n["text"],
            index=i,
            raw_role=n["raw_role"],
            render_kind=n["render_kind"],
            created_at=n["created_at"],
            updated_at=n["updated_at"],
            extra=n["extra"],
        ))

    return make_conversation(
        uuid=conv_id,
        name=name,
        messages=messages,
        created_at=created_at,
        updated_at=updated_at,
        source={"platform": "chatgpt"},
    )


def load_export(path: Path) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if isinstance(data, dict):
        # 単一会話の場合
        return [data]
    if not isinstance(data, list):
        raise ValueError(
            f"想定外のトップレベル型: {type(data).__name__}.")
    return data


def parse_file(export_path: Path) -> list[NormalizedConv]:
    raw_list = load_export(Path(export_path))
    return [normalize_conv(r) for r in raw_list]


def parse_folder(input_dir: Path) -> list[NormalizedConv]:
    """
    フォルダ内のすべての conversations-*.json を読み、会話を結合して返す。
    """
    input_dir = Path(input_dir)
    if not input_dir.exists():
        raise FileNotFoundError(f"フォルダがありません: {input_dir}")
    convs: list[NormalizedConv] = []
    for p in sorted(input_dir.iterdir()):
        if p.suffix == ".json" and not p.name.startswith("_"):
            convs.extend(parse_file(p))
    return convs
