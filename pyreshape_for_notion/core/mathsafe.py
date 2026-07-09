"""
pyreshape_for_notion.core.mathsafe

Markdown テキストを「数式・コード・素のテキスト」に安全に切り分けるための
スキャナ層。すべての数式変換 (md 書き換え / Notion ブロック化) は本モジュールの
セグメント列を唯一の入力とし、正規表現の直接適用を避ける。

なぜ独立モジュールにするか (pcp_000 の設計判断):
  数式変換のバグの大半は「保護すべき領域を保護し損ねる」ことから生じる。
  すなわち、コードフェンス内の ``$``、インラインコード内の ``\\mathsf T``、
  エスケープされた ``\\$`` などを数式と誤認する。これらの判定を一箇所に
  集約し、下流の変換器は「セグメントの種類」だけを見れば済むようにする。

セグメントの種類:
  "text"        : 素のテキスト (Markdown のインライン記法を含む)
  "fence"       : コードフェンス ```` ```lang ... ``` ````
  "inline_code" : インラインコード `` `...` ``
  "math_inline" : インライン数式 ``$...$`` / ``\\(...\\)``
  "math_block"  : ブロック数式 ``$$...$$`` / ``\\[...\\]``

不変条件:
  "".join(seg.raw for seg in iter_segments(t)) == t
  (原文を一字一句復元できる。テストで検証する)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = [
    "Segment",
    "iter_segments",
    "reassemble",
    "wrap_inline_code",
    "fence_block",
    "MATH_KINDS",
    "PROTECTED_KINDS",
]

MATH_KINDS = ("math_inline", "math_block")
PROTECTED_KINDS = ("fence", "inline_code")

_FENCE_OPEN_RE = re.compile(r"^(?P<indent>\s{0,3})(?P<mark>`{3,}|~{3,})(?P<info>.*)$")


@dataclass
class Segment:
    kind: str
    raw: str                      # 原文そのまま (復元用)
    content: str = ""             # 中身 (デリミタを除いたもの)
    info: str = ""                # fence の言語指定など
    field_meta: dict = field(default_factory=dict)

    @property
    def is_math(self) -> bool:
        return self.kind in MATH_KINDS


# ============================================================
# フェンス分割 (行単位)
# ============================================================
def _split_fences(text: str) -> list[tuple[str, str]]:
    """
    ("fence", raw) と ("plain", raw) の列に分ける。
    未閉のフェンスは plain として扱う (文書破壊を避けるため)。
    """
    lines = text.splitlines(keepends=True)
    out: list[tuple[str, str]] = []
    buf: list[str] = []
    i, n = 0, len(lines)

    while i < n:
        m = _FENCE_OPEN_RE.match(lines[i].rstrip("\n"))
        if not m:
            buf.append(lines[i])
            i += 1
            continue

        mark = m.group("mark")
        close_re = re.compile(r"^\s{0,3}" + re.escape(mark[0]) + "{" + str(len(mark)) + r",}\s*$")
        j = i + 1
        while j < n and not close_re.match(lines[j].rstrip("\n")):
            j += 1

        if j >= n:  # 未閉フェンス → 通常テキスト扱い
            buf.append(lines[i])
            i += 1
            continue

        if buf:
            out.append(("plain", "".join(buf)))
            buf = []
        out.append(("fence", "".join(lines[i:j + 1])))
        i = j + 1

    if buf:
        out.append(("plain", "".join(buf)))
    return out


def _fence_parts(raw: str) -> tuple[str, str]:
    """フェンス raw から (info, content) を取り出す。"""
    lines = raw.splitlines(keepends=True)
    m = _FENCE_OPEN_RE.match(lines[0].rstrip("\n"))
    info = (m.group("info").strip() if m else "")
    body = "".join(lines[1:-1]) if len(lines) >= 2 else ""
    return info, body


# ============================================================
# インライン走査 (文字単位)
# ============================================================
def _find_inline_close_dollar(s: str, start: int) -> int:
    """
    s[start] が開き ``$`` の次の位置。閉じ ``$`` の index を返す。見つからなければ -1。

    規則 (CommonMark 系の数式拡張に準拠):
      - 閉じ ``$`` の直前は空白であってはならない
      - 空行 (``\\n\\n``) をまたがない
      - ``\\x`` は 2 文字まとめて読み飛ばす (``\\$`` を数式終端と誤認しないため)
    """
    j, n = start, len(s)
    while j < n:
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "\n" and s.startswith("\n", j + 1):
            return -1
        if c == "\n" and j + 1 < n and s[j + 1 :].lstrip(" \t").startswith("\n"):
            return -1
        if c == "$":
            if j > start and not s[j - 1].isspace():
                return j
            j += 1
            continue
        j += 1
    return -1


def _scan_plain(s: str, latex_delims: bool = True, dollar_math: bool = True) -> list[Segment]:
    out: list[Segment] = []
    buf: list[str] = []
    i, n = 0, len(s)

    def flush() -> None:
        if buf:
            out.append(Segment("text", "".join(buf)))
            buf.clear()

    while i < n:
        ch = s[i]

        # --- LaTeX 標準デリミタ / エスケープ ---
        if ch == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if latex_delims and nxt == "[":
                j = s.find("\\]", i + 2)
                if j != -1:
                    flush()
                    out.append(Segment("math_block", s[i:j + 2], s[i + 2:j]))
                    i = j + 2
                    continue
            if latex_delims and nxt == "(":
                j = s.find("\\)", i + 2)
                if j != -1 and "\n\n" not in s[i + 2:j]:
                    flush()
                    out.append(Segment("math_inline", s[i:j + 2], s[i + 2:j]))
                    i = j + 2
                    continue
            buf.append(s[i:i + 2])       # ``\$`` などのエスケープを温存
            i += 2
            continue

        # --- インラインコード ---
        if ch == "`":
            run = re.match(r"`+", s[i:]).group(0)
            j = i + len(run)
            while True:
                j = s.find(run, j)
                if j == -1:
                    break
                if j + len(run) < n and s[j + len(run)] == "`":
                    j += len(run) + 1
                    continue
                break
            if j != -1:
                flush()
                out.append(Segment("inline_code", s[i:j + len(run)], s[i + len(run):j]))
                i = j + len(run)
                continue
            buf.append(ch)
            i += 1
            continue

        # --- 数式 ---
        if ch == "$" and dollar_math:
            if s.startswith("$$", i):
                j = s.find("$$", i + 2)
                if j != -1:
                    flush()
                    out.append(Segment("math_block", s[i:j + 2], s[i + 2:j]))
                    i = j + 2
                    continue
            elif i + 1 < n and not s[i + 1].isspace():
                j = _find_inline_close_dollar(s, i + 1)
                if j != -1:
                    flush()
                    out.append(Segment("math_inline", s[i:j + 1], s[i + 1:j]))
                    i = j + 1
                    continue
            buf.append(ch)
            i += 1
            continue

        buf.append(ch)
        i += 1

    flush()
    return out


def iter_segments(
    text: str,
    latex_delims: bool = True,
    dollar_math: bool = True,
) -> list[Segment]:
    """Markdown 全文をセグメント列に分解する。"""
    segs: list[Segment] = []
    for kind, raw in _split_fences(text):
        if kind == "fence":
            info, content = _fence_parts(raw)
            segs.append(Segment("fence", raw, content, info))
        else:
            segs.extend(_scan_plain(raw, latex_delims, dollar_math))
    return segs


def reassemble(segs: list[Segment]) -> str:
    return "".join(s.raw for s in segs)


# ============================================================
# 出力ヘルパ
# ============================================================
def wrap_inline_code(content: str, keep_dollar: bool = True) -> str:
    """
    LaTeX 断片を、Notion が絶対に壊さないインラインコードに包む。
    バッククォートの衝突と、改行をまたぐ数式 (原文の折り返し) を吸収する。
    """
    body = re.sub(r"[ \t]*\n[ \t]*", " ", content).strip()
    if keep_dollar:
        body = f"${body}$"
    runs = re.findall(r"`+", body)
    ticks = "`" * ((max(len(r) for r in runs) + 1) if runs else 1)
    pad = " " if body.startswith("`") or body.endswith("`") else ""
    return f"{ticks}{pad}{body}{pad}{ticks}"


def fence_block(content: str, lang: str = "latex") -> str:
    """LaTeX 断片をコードフェンスに包む (内部の ``` と衝突しない長さを選ぶ)。"""
    body = content.strip("\n").rstrip()
    runs = re.findall(r"`{3,}", body)
    mark = "`" * ((max(len(r) for r in runs) + 1) if runs else 3)
    return f"{mark}{lang}\n{body}\n{mark}"
