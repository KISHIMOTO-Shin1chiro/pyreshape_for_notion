"""
pyreshape_for_notion.artifact.notion_blocks

Markdown を Notion API のブロックオブジェクト列に変換する。
md インポータを迂回するため、数式は ``equation`` ブロック / ``equation``
リッチテキストとして構成され、Notion 上で KaTeX により実際にレンダリングされる。

本モジュールは外部依存を持たない。返り値は素の dict / list であり、
``requests`` でも公式 SDK でも Notion MCP でも、そのまま送信できる。

対応ブロック:
  heading_1..3 / paragraph / bulleted_list_item / numbered_list_item /
  code / equation / divider / quote / table (+ table_row)

対応インライン:
  equation (``$...$``) / code (`` `...` ``) / bold (``**...**``) /
  italic (``*...*``) / link (``[t](u)``)

設計上の注意 (pcp_000):
  1. 強調とリンクの走査は「保護領域 (数式・インラインコード) をマスクした
     写像上」で行う。そうしないと ``**$^{\\intercal}$ へ改記**`` のように
     強調が数式をまたぐ場合に閉じ記号を見失う。
  2. ``_`` による強調は解釈しない。``pcp_002_008`` のような識別子を
     イタリック化してしまうため (GFM の intraword 規則を自前実装するより
     無効化するほうが安全側)。
  3. ``restore_coded_math`` が真のとき、``md_rewrite`` が退避のために作った
     `` `$...$` `` と ```` ```latex ```` を数式へ復元する。

API 上の制約 (2026-03 時点の公開仕様):
  - rich_text の 1 要素あたり content は 2000 文字まで → 自動分割する
  - 1 リクエストあたり children は 100 ブロックまで → ``chunk_blocks`` を用意
"""

from __future__ import annotations

import re

from ..core.mathsafe import iter_segments

__all__ = [
    "markdown_to_blocks",
    "make_page_payload",
    "chunk_blocks",
    "extract_title",
    "MAX_RICH_TEXT",
    "MAX_CHILDREN",
]

MAX_RICH_TEXT = 2000
MAX_CHILDREN = 100

_ATX_RE = re.compile(r"^(#{1,6})[ \t]+(.*)$")
_FENCE_OPEN_RE = re.compile(r"^\s{0,3}(?P<mark>`{3,}|~{3,})(?P<info>.*)$")
_HR_RE = re.compile(r"^\s{0,3}(-{3,}|\*{3,}|_{3,})\s*$")
_BULLET_RE = re.compile(r"^\s{0,3}[-*+][ \t]+(.*)$")
_ORDERED_RE = re.compile(r"^\s{0,3}\d{1,9}[.)][ \t]+(.*)$")
_QUOTE_RE = re.compile(r"^\s{0,3}>[ \t]?(.*)$")
_TABLE_ROW_RE = re.compile(r"^\s{0,3}\|(.*)\|\s*$")
_TABLE_SEP_RE = re.compile(r"^\s{0,3}\|[\s:|-]+\|\s*$")
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_CODED_MATH_RE = re.compile(r"^\s*\$(?P<expr>.+)\$\s*$", re.DOTALL)

_CJK_RE = re.compile(
    r"[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]"
)

_NOTION_LANGS = {
    "abap", "bash", "c", "c#", "c++", "clojure", "coffeescript", "css", "dart",
    "diff", "docker", "elixir", "elm", "erlang", "fortran", "go", "graphql",
    "groovy", "haskell", "html", "java", "javascript", "json", "julia", "kotlin",
    "latex", "less", "lisp", "lua", "makefile", "markdown", "matlab", "mermaid",
    "nix", "objective-c", "ocaml", "pascal", "perl", "php", "plain text",
    "powershell", "prolog", "protobuf", "python", "r", "ruby", "rust", "sass",
    "scala", "scheme", "scss", "shell", "sql", "swift", "toml", "typescript",
    "vb.net", "verilog", "vhdl", "xml", "yaml",
}
_LANG_ALIAS = {
    "py": "python", "js": "javascript", "ts": "typescript", "sh": "shell",
    "text": "plain text", "txt": "plain text", "": "plain text",
    "tex": "latex", "console": "shell",
}


# ============================================================
# rich_text の構成部品
# ============================================================
def _ann(bold: bool = False, italic: bool = False, code: bool = False) -> dict:
    return {
        "bold": bold, "italic": italic, "strikethrough": False,
        "underline": False, "code": code, "color": "default",
    }


def _text_runs(s: str, ann: dict, link: str | None = None) -> list[dict]:
    runs: list[dict] = []
    for k in range(0, len(s), MAX_RICH_TEXT):
        chunk = s[k:k + MAX_RICH_TEXT]
        t: dict = {"type": "text", "text": {"content": chunk}, "annotations": dict(ann)}
        if link:
            t["text"]["link"] = {"url": link}
        runs.append(t)
    return runs


def _equation_run(expr: str, ann: dict) -> dict:
    expr = re.sub(r"[ \t]*\n[ \t]*", " ", expr).strip()
    return {
        "type": "equation",
        "equation": {"expression": expr[:MAX_RICH_TEXT]},
        "annotations": dict(ann),
    }


# ============================================================
# インライン解析: 保護領域をマスクしたうえで強調・リンクを走査する
# ============================================================
def _span_table(s: str):
    spans: list[tuple[int, int, object]] = []
    mask = list(s)
    pos = 0
    for seg in iter_segments(s):
        end = pos + len(seg.raw)
        spans.append((pos, end, seg))
        if seg.kind != "text":
            for k in range(pos, end):
                mask[k] = "\x00"
        pos = end
    return spans, "".join(mask)


def _parse_inline(s: str, ann: dict | None = None, restore: bool = True) -> list[dict]:
    ann = ann or _ann()
    if not s:
        return []

    spans, mask = _span_table(s)
    owner = [-1] * (len(s) + 1)
    for idx, (st, en, _seg) in enumerate(spans):
        for k in range(st, en):
            owner[k] = idx

    out: list[dict] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            out.extend(_text_runs("".join(buf), ann))
            buf.clear()

    i, n = 0, len(s)
    while i < n:
        seg = spans[owner[i]][2] if owner[i] >= 0 else None

        # --- 保護領域 (数式 / インラインコード / フェンス) ---
        if seg is not None and seg.kind != "text":
            _st, en, _ = spans[owner[i]]
            flush()
            if seg.kind == "inline_code":
                m = _CODED_MATH_RE.match(seg.content) if restore else None
                if m:
                    out.append(_equation_run(m.group("expr"), ann))
                else:
                    out.extend(_text_runs(seg.content, _ann(ann["bold"], ann["italic"], code=True)))
            elif seg.kind in ("math_inline", "math_block"):
                out.append(_equation_run(seg.content, ann))
            else:  # フェンスが行内に紛れ込んだ場合の保険
                out.extend(_text_runs(seg.raw, ann))
            i = en
            continue

        # --- 素のテキスト ---
        ch = s[i]
        if ch == "\\" and i + 1 < n:
            buf.append(s[i + 1])
            i += 2
            continue

        if mask.startswith("**", i):
            j = mask.find("**", i + 2)
            if j > i + 2:
                flush()
                out.extend(_parse_inline(s[i + 2:j], _ann(True, ann["italic"]), restore))
                i = j + 2
                continue

        if ch == "*" and not mask.startswith("**", i):
            j = mask.find("*", i + 1)
            if j > i + 1:
                flush()
                out.extend(_parse_inline(s[i + 1:j], _ann(ann["bold"], True), restore))
                i = j + 1
                continue

        if ch == "[":
            m = _LINK_RE.match(mask, i)
            if m:
                flush()
                label = s[m.start(1):m.end(1)]
                url = s[m.start(2):m.end(2)]
                if label:
                    out.extend(_text_runs(label, ann, link=url))
                i = m.end()
                continue

        buf.append(ch)
        i += 1

    flush()
    return out


# ============================================================
# 段落結合 (日本語のハードラップ対策)
# ============================================================
def _join_lines(lines: list[str], mode: str = "smart") -> str:
    lines = [l for l in lines if l.strip()]
    if not lines:
        return ""
    if mode == "newline":
        return "\n".join(l.rstrip() for l in lines)
    if mode == "space":
        return " ".join(l.strip() for l in lines)
    out = lines[0].strip()
    for ln in lines[1:]:
        ln = ln.strip()
        if out and _CJK_RE.search(out[-1]) and _CJK_RE.search(ln[0]):
            out += ln
        else:
            out += (" " if out else "") + ln
    return out


# ============================================================
# ブロック生成
# ============================================================
def _blk(btype: str, payload: dict) -> dict:
    return {"object": "block", "type": btype, btype: payload}


def _normalize_lang(info: str) -> str:
    lang = (info.split()[0] if info.strip() else "").lower()
    lang = _LANG_ALIAS.get(lang, lang)
    return lang if lang in _NOTION_LANGS else "plain text"


def _table_cells(row: str) -> list[str]:
    inner = _TABLE_ROW_RE.match(row).group(1)
    cells: list[str] = []
    cur: list[str] = []
    i = 0
    while i < len(inner):
        c = inner[i]
        if c == "\\" and i + 1 < len(inner) and inner[i + 1] == "|":
            cur.append("|")
            i += 2
            continue
        if c == "|":
            cells.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    cells.append("".join(cur))
    return [c.strip() for c in cells]


def markdown_to_blocks(
    text: str,
    paragraph_join: str = "smart",
    skip_first_h1: bool = False,
    restore_coded_math: bool = True,
) -> list[dict]:
    """
    Markdown を Notion API のブロック配列に変換する。

      paragraph_join     : "smart" (和文は空白なしで連結) | "space" | "newline"
      skip_first_h1      : 先頭の H1 を本文から外す (ページタイトルへ回す用)
      restore_coded_math : `` `$...$` `` と ```` ```latex ```` を数式に復元する
                           (md_rewrite で退避した文書を読み戻すため。既定 True)
    """
    lines = text.replace("\r\n", "\n").split("\n")
    blocks: list[dict] = []
    para: list[str] = []
    i, n = 0, len(lines)
    seen_h1 = False

    def inline(s: str) -> list[dict]:
        return _parse_inline(s, None, restore_coded_math)

    def flush_para() -> None:
        if para:
            joined = _join_lines(para, paragraph_join)
            if joined:
                blocks.append(_blk("paragraph", {"rich_text": inline(joined)}))
            para.clear()

    while i < n:
        ln = lines[i]

        if not ln.strip():
            flush_para()
            i += 1
            continue

        # --- ブロック数式 ($$ 単独行) ---
        if ln.strip() == "$$":
            flush_para()
            j = i + 1
            body: list[str] = []
            while j < n and lines[j].strip() != "$$":
                body.append(lines[j])
                j += 1
            blocks.append(_blk("equation", {"expression": "\n".join(body).strip()[:MAX_RICH_TEXT]}))
            i = j + 1
            continue

        # --- コードフェンス ---
        m = _FENCE_OPEN_RE.match(ln)
        if m:
            flush_para()
            mark, info = m.group("mark"), m.group("info")
            close = re.compile(r"^\s{0,3}" + re.escape(mark[0]) + "{" + str(len(mark)) + r",}\s*$")
            j = i + 1
            body = []
            while j < n and not close.match(lines[j]):
                body.append(lines[j])
                j += 1
            code = "\n".join(body)
            lang = _normalize_lang(info)
            if lang == "latex" and restore_coded_math:
                blocks.append(_blk("equation", {"expression": code.strip()[:MAX_RICH_TEXT]}))
            else:
                blocks.append(_blk("code", {
                    "rich_text": _text_runs(code, _ann()) or _text_runs("", _ann()),
                    "language": lang,
                }))
            i = j + 1
            continue

        # --- 見出し ---
        m = _ATX_RE.match(ln)
        if m:
            flush_para()
            level = len(m.group(1))
            body_text = m.group(2).strip()
            if level == 1 and skip_first_h1 and not seen_h1:
                seen_h1 = True
                i += 1
                continue
            if level == 1:
                seen_h1 = True
            if level > 3:
                blocks.append(_blk("paragraph", {"rich_text": inline(f"**{body_text}**")}))
            else:
                blocks.append(_blk(f"heading_{level}", {
                    "rich_text": inline(body_text), "is_toggleable": False,
                }))
            i += 1
            continue

        # --- 水平線 ---
        if _HR_RE.match(ln):
            flush_para()
            blocks.append(_blk("divider", {}))
            i += 1
            continue

        # --- 表 ---
        if _TABLE_ROW_RE.match(ln) and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1]):
            flush_para()
            header = _table_cells(ln)
            width = len(header)
            rows = [header]
            j = i + 2
            while j < n and _TABLE_ROW_RE.match(lines[j]) and not _TABLE_SEP_RE.match(lines[j]):
                cells = (_table_cells(lines[j]) + [""] * width)[:width]
                rows.append(cells)
                j += 1
            blocks.append(_blk("table", {
                "table_width": width,
                "has_column_header": True,
                "has_row_header": False,
                "children": [
                    _blk("table_row", {"cells": [inline(c) for c in r]}) for r in rows
                ],
            }))
            i = j
            continue

        # --- 引用 ---
        m = _QUOTE_RE.match(ln)
        if m:
            flush_para()
            body = [m.group(1)]
            j = i + 1
            while j < n and _QUOTE_RE.match(lines[j]):
                body.append(_QUOTE_RE.match(lines[j]).group(1))
                j += 1
            blocks.append(_blk("quote", {"rich_text": inline(_join_lines(body, paragraph_join))}))
            i = j
            continue

        # --- リスト ---
        m = _BULLET_RE.match(ln)
        if m:
            flush_para()
            blocks.append(_blk("bulleted_list_item", {"rich_text": inline(m.group(1))}))
            i += 1
            continue
        m = _ORDERED_RE.match(ln)
        if m:
            flush_para()
            blocks.append(_blk("numbered_list_item", {"rich_text": inline(m.group(1))}))
            i += 1
            continue

        para.append(ln)
        i += 1

    flush_para()
    return blocks


# ============================================================
# ページ生成用ペイロード
# ============================================================
def extract_title(text: str, fallback: str = "Untitled") -> str:
    for ln in text.split("\n"):
        m = _ATX_RE.match(ln)
        if m and len(m.group(1)) == 1:
            return m.group(2).strip() or fallback
    return fallback


def chunk_blocks(blocks: list[dict], size: int = MAX_CHILDREN) -> list[list[dict]]:
    return [blocks[k:k + size] for k in range(0, len(blocks), size)]


def make_page_payload(parent_page_id: str, title: str, blocks: list[dict]) -> dict:
    """
    POST /v1/pages の本体。children は先頭 100 ブロックのみ含める。
    残りは PATCH /v1/blocks/{page_id}/children に ``chunk_blocks`` の続きを送る。
    """
    return {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": title[:2000]}}]}
        },
        "children": blocks[:MAX_CHILDREN],
    }
