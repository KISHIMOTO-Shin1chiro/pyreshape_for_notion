"""
pyreshape_for_notion.gemini.parser

Gemini (AI Chat Exporter Chrome 拡張) の MD ファイルをパースし、
正規化済み会話 (NormalizedConv) を生成する。

入力: {YYYY-MM-DD}_{title}.md (1 ファイル = 1 会話)
会話 ID: ファイル名の SHA-1 先頭 12 文字 (元データに UUID が無いため)
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from ..core.schema import NormalizedConv, make_conversation, make_message

JST = timezone(timedelta(hours=9))

H1_HEADER_RE     = re.compile(r"^#\s+Gemini Chat Export\s*$")
EXPORTED_ON_RE   = re.compile(r"^>\s*Exported on:\s*(.+?)\s*$")
USER_HEADER_RE   = re.compile(r"^##\s+\U0001F464\s+You\s*$")     # 👤
GEMINI_HEADER_RE = re.compile(r"^##\s+\U0001F916\s+Gemini\s*$")  # 🤖
SEPARATOR_RE     = re.compile(r"^---\s*$")
FENCE_RE         = re.compile(r"^\s*```")
DATE_PREFIX_RE   = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+)$")


def parse_filename(filename: str) -> tuple[str | None, str]:
    stem = Path(filename).stem
    m = DATE_PREFIX_RE.match(stem)
    if m:
        return m.group(1), m.group(2).replace("_", " ")
    return None, stem.replace("_", " ")


def compute_conv_id(filename: str, length: int = 12) -> str:
    return hashlib.sha1(filename.encode("utf-8")).hexdigest()[:length]


def _parse_exported_on(s: str | None) -> str:
    if not s:
        return ""
    s = s.strip()
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=JST).isoformat()
        except ValueError:
            continue
    return ""


def _parse_date_prefix(date_str: str | None) -> str:
    if not date_str:
        return ""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(
            tzinfo=JST).isoformat()
    except ValueError:
        return ""


def parse_gemini_md(text: str) -> dict[str, Any]:
    """Gemini Chat Export 形式の MD をパース。"""
    lines = text.splitlines()
    state = "HEADER"
    exported_on: str | None = None
    messages: list[dict[str, Any]] = []
    in_fence = False
    current_sender: str | None = None
    current_lines: list[str] = []

    def _flush() -> None:
        nonlocal current_sender, current_lines
        if current_sender is None:
            return
        body = "\n".join(current_lines).strip()
        messages.append({"sender": current_sender, "text": body})
        current_sender = None
        current_lines = []

    for line in lines:
        is_fence_line = bool(FENCE_RE.match(line))
        if in_fence:
            if is_fence_line:
                in_fence = False
            if current_sender is not None:
                current_lines.append(line)
            continue
        if is_fence_line:
            in_fence = True
            if current_sender is not None:
                current_lines.append(line)
            continue
        if state == "HEADER":
            if H1_HEADER_RE.match(line):
                continue
            m = EXPORTED_ON_RE.match(line)
            if m:
                exported_on = m.group(1).strip()
                continue
            if USER_HEADER_RE.match(line):
                state = "BODY"
                current_sender = "human"
                current_lines = []
                continue
            continue
        if USER_HEADER_RE.match(line):
            _flush()
            current_sender = "human"
            continue
        if GEMINI_HEADER_RE.match(line):
            _flush()
            current_sender = "assistant"
            continue
        if SEPARATOR_RE.match(line):
            _flush()
            continue
        if current_sender is not None:
            current_lines.append(line)

    _flush()
    return {"exported_on": exported_on, "messages": messages}


def parse_file(md_path: Path) -> NormalizedConv:
    """1 つの MD ファイルから正規化会話を構築する。"""
    text = md_path.read_text(encoding="utf-8")
    parsed = parse_gemini_md(text)

    filename = md_path.name
    date_prefix, title = parse_filename(filename)
    conv_id = compute_conv_id(filename)

    created_at = _parse_date_prefix(date_prefix)
    updated_at = _parse_exported_on(parsed["exported_on"])
    if not created_at:
        created_at = updated_at
    if not updated_at:
        updated_at = created_at

    messages = []
    for i, m in enumerate(parsed["messages"]):
        messages.append(make_message(
            uuid=f"{conv_id}:{i:04d}",
            sender=m["sender"],
            text=m["text"] or "",
            index=i,
            created_at=created_at,
            updated_at=updated_at,
        ))

    return make_conversation(
        uuid=conv_id,
        name=title,
        messages=messages,
        created_at=created_at,
        updated_at=updated_at,
        source={
            "platform": "gemini",
            "original_filename": filename,
            "exported_on_raw": parsed["exported_on"],
        },
    )


def parse_folder(input_dir: Path) -> list[NormalizedConv]:
    """フォルダ内のすべての .md を正規化会話のリストにする。"""
    if not input_dir.exists():
        raise FileNotFoundError(f"フォルダがありません: {input_dir}")
    md_files = sorted(
        p for p in input_dir.iterdir()
        if p.is_file() and p.suffix == ".md" and not p.name.startswith("_")
    )
    return [parse_file(p) for p in md_files]
