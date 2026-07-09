"""
pyreshape_for_notion.artifact.md_rewrite

Claude の Artifacts として生成された単体の Markdown 文書を、
Notion の「Import → Text & Markdown」で壊れずに取り込める Markdown に
書き換える。

対象とする不具合 (pcp_000 で報告):
  Notion の Markdown インポータは ``$...$`` / ``$$...$$`` を数式として
  安定に解釈しない。実測では、多くの数式スパンが本文中に ``$true$`` という
  文字列として現れる。これは KaTeX のレンダリング失敗ではなく、インポータの
  インライン規則が「照合したか否かの真偽値」をそのまま本文に書き出している
  ことを示唆する挙動である (デリミタは残り、中身だけが ``true`` になる)。
  いずれにせよ、md 経路では数式の中身が失われる。

方針:
  A. 数式の「中身」を最優先で救う。中身が消えるくらいなら、レンダリングを
     諦めてソースを保存する。
     → インライン数式は インラインコード、ブロック数式は ```latex フェンス。
       コード領域はインポータが一切解釈しないため、原文が完全に保存される。
  B. レンダリングまで欲しい場合は md 経路を使わない。
     → ``artifact.notion_blocks.markdown_to_blocks`` で Notion API の
       equation ブロックを直接構成する (本モジュールの姉妹)。

math_mode:
  "code"  : (既定) 数式をコード化して確実に保存する
  "keep"  : 数式をそのまま残す (Notion 側が修正された場合 / API 経路の前処理)
  "strip" : デリミタを外して素のテキストにする (可読性優先・非可逆)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from pathlib import Path

from ..core.mathsafe import (
    Segment,
    iter_segments,
    wrap_inline_code,
    fence_block,
)

__all__ = [
    "RewriteStats",
    "rewrite_for_notion",
    "convert_file",
    "convert_folder",
]

_UNSUPPORTED_KEY = "This block is not supported"
_ATX_RE = re.compile(r"^(#{1,6})[ \t]+(.*)$")
_FENCE_LINE_RE = re.compile(r"^\s{0,3}(```|~~~)")
_HR_RE = re.compile(r"^\s{0,3}(-{3,}|\*{3,}|_{3,})\s*$")
_TABLE_ROW_RE = re.compile(r"^\s{0,3}\|")

MAX_NOTION_HEADING = 3


@dataclass
class RewriteStats:
    math_inline: int = 0
    math_block: int = 0
    latex_delims_normalized: int = 0
    headings_demoted: int = 0
    unsupported_removed: int = 0
    table_pipes_escaped: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


# ============================================================
# 1. "This block is not supported" プレースホルダの除去
# ============================================================
def _remove_unsupported(text: str) -> tuple[str, int]:
    lines = text.splitlines()
    out: list[str] = []
    removed = 0
    i, n = 0, len(lines)
    while i < n:
        if _FENCE_LINE_RE.match(lines[i]):
            j = i + 1
            body: list[str] = []
            while j < n and not _FENCE_LINE_RE.match(lines[j]):
                body.append(lines[j])
                j += 1
            if _UNSUPPORTED_KEY in "\n".join(body) and len(body) <= 3:
                removed += 1
                i = j + 1
                continue
            out.append(lines[i])
            out.extend(body)
            if j < n:
                out.append(lines[j])
            i = j + 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out), removed


# ============================================================
# 2. 数式セグメントの書き換え
# ============================================================
def _rewrite_math(
    text: str,
    math_mode: str,
    keep_dollar: bool,
    fence_lang: str,
    stats: RewriteStats,
) -> str:
    segs = iter_segments(text)
    out: list[str] = []

    for s in segs:
        if not s.is_math:
            out.append(s.raw)
            continue

        # ``\(...\)`` / ``\[...\]`` からの正規化を計上
        if not s.raw.startswith("$"):
            stats.latex_delims_normalized += 1

        if s.kind == "math_inline":
            stats.math_inline += 1
            if math_mode == "code":
                out.append(wrap_inline_code(s.content, keep_dollar=keep_dollar))
            elif math_mode == "keep":
                out.append("$" + s.content.strip() + "$")
            else:  # strip
                out.append(s.content.strip())
        else:
            stats.math_block += 1
            if math_mode == "code":
                out.append(fence_block(s.content, lang=fence_lang))
            elif math_mode == "keep":
                out.append("$$\n" + s.content.strip("\n").strip() + "\n$$")
            else:
                out.append(s.content.strip())

    return "".join(out)


# ============================================================
# 3. ブロック数式フェンスの前後に空行を確保
# ============================================================
def _isolate_block_fences(text: str, fence_lang: str) -> str:
    """
    段落の途中に現れた ```latex フェンスが直前行と癒着しないよう空行を入れる。
    (``$$`` が行頭でない位置に置かれていた場合に発生する)
    """
    lines = text.split("\n")
    out: list[str] = []
    opener = "```" + fence_lang
    for ln in lines:
        idx = ln.find(opener)
        if idx > 0:                      # 行頭以外にフェンスが出現
            head, tail = ln[:idx].rstrip(), ln[idx:]
            if head:
                out.append(head)
                out.append("")
            out.append(tail)
            continue
        out.append(ln)
    # 閉じフェンスの直後に本文が続く場合の分離
    fixed: list[str] = []
    for k, ln in enumerate(out):
        fixed.append(ln)
        if ln.strip() == "```" and k + 1 < len(out) and out[k + 1].strip():
            fixed.append("")
    return "\n".join(fixed)


# ============================================================
# 4. 見出しの降格 (Notion は H3 まで)
# ============================================================
def _demote_headings(text: str, stats: RewriteStats) -> str:
    lines = text.split("\n")
    out: list[str] = []
    in_fence = False
    for ln in lines:
        if _FENCE_LINE_RE.match(ln):
            in_fence = not in_fence
            out.append(ln)
            continue
        if in_fence:
            out.append(ln)
            continue
        m = _ATX_RE.match(ln)
        if m and len(m.group(1)) > MAX_NOTION_HEADING:
            body = m.group(2).strip()
            stats.headings_demoted += 1
            out.append(f"**{body}**" if body else "")
            continue
        out.append(ln)
    return "\n".join(out)


# ============================================================
# 5. 表の行に含まれるコードスパン内の ``|`` をエスケープ
# ============================================================
def _escape_table_pipes(text: str, stats: RewriteStats) -> str:
    lines = text.split("\n")
    out: list[str] = []
    in_fence = False
    for ln in lines:
        if _FENCE_LINE_RE.match(ln):
            in_fence = not in_fence
            out.append(ln)
            continue
        if in_fence or not _TABLE_ROW_RE.match(ln):
            out.append(ln)
            continue

        def _fix(m: re.Match) -> str:
            inner = m.group(0)
            if "|" not in inner:
                return inner
            stats.table_pipes_escaped += inner.count("|")
            return inner.replace("|", r"\|")

        out.append(re.sub(r"`+[^`\n]*?`+", _fix, ln))
    return "\n".join(out)


# ============================================================
# 6. 空行の整理
# ============================================================
def _normalize_blanks(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = text.split("\n")
    out: list[str] = []
    in_fence = False
    for k, ln in enumerate(lines):
        if _FENCE_LINE_RE.match(ln):
            in_fence = not in_fence
            out.append(ln)
            continue
        if not in_fence and _HR_RE.match(ln):
            if out and out[-1].strip() != "":
                out.append("")
            out.append(ln)
            if k + 1 < len(lines) and lines[k + 1].strip() != "":
                out.append("")
            continue
        out.append(ln)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out))


# ============================================================
# 公開 API
# ============================================================
def rewrite_for_notion(
    text: str,
    math_mode: str = "code",
    keep_dollar: bool = True,
    fence_lang: str = "latex",
    demote_headings: bool = True,
    remove_unsupported: bool = True,
    escape_table_pipes: bool = True,
    normalize_blanks: bool = True,
) -> tuple[str, RewriteStats]:
    """
    Claude Artifact の Markdown を Notion インポート安全な Markdown に書き換える。

    引数:
      math_mode          : "code" | "keep" | "strip"
      keep_dollar        : "code" のとき、インラインコード内に ``$`` を残すか。
                           True にしておくと後段で数式へ復元できる (既定)。
      fence_lang         : ブロック数式のフェンス言語 (既定 "latex")
      demote_headings    : H4 以降を太字段落へ降格する (Notion は H3 まで)
      remove_unsupported : "This block is not supported" フェンスを除去
      escape_table_pipes : 表の行のコードスパン内の ``|`` を ``\\|`` に
      normalize_blanks   : 連続空行の圧縮と水平線の前後の空行確保

    返り値:
      (書き換え後テキスト, 統計)
    """
    if math_mode not in ("code", "keep", "strip"):
        raise ValueError(f"math_mode は 'code' | 'keep' | 'strip' のいずれか: {math_mode!r}")

    stats = RewriteStats()

    if remove_unsupported:
        text, stats.unsupported_removed = _remove_unsupported(text)

    text = _rewrite_math(text, math_mode, keep_dollar, fence_lang, stats)

    if math_mode == "code":
        text = _isolate_block_fences(text, fence_lang)
    if demote_headings:
        text = _demote_headings(text, stats)
    if escape_table_pipes:
        text = _escape_table_pipes(text, stats)
    if normalize_blanks:
        text = _normalize_blanks(text)

    return text.rstrip() + "\n", stats


def convert_file(
    src: str | Path,
    dst: str | Path | None = None,
    suffix: str = "_notion",
    **kwargs,
) -> tuple[Path, RewriteStats]:
    """単一の md ファイルを変換して書き出す。dst 省略時は同階層に ``*_notion.md``。"""
    src = Path(src)
    text = src.read_text(encoding="utf-8-sig")
    out_text, stats = rewrite_for_notion(text, **kwargs)
    if dst is None:
        dst = src.with_name(src.stem + suffix + src.suffix)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(out_text, encoding="utf-8")
    return dst, stats


def convert_folder(
    src_dir: str | Path,
    dst_dir: str | Path,
    pattern: str = "*.md",
    **kwargs,
) -> list[tuple[Path, RewriteStats]]:
    """フォルダ内の md をまとめて変換する。"""
    src_dir, dst_dir = Path(src_dir), Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    results: list[tuple[Path, RewriteStats]] = []
    for p in sorted(src_dir.glob(pattern)):
        out, stats = convert_file(p, dst_dir / p.name, **kwargs)
        results.append((out, stats))
    return results
