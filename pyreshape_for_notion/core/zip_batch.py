"""
pyreshape_for_notion.core.zip_batch

Notion 用 MD 群を zip バッチに小分けする処理 (Code_007/008 相当)。

Notion の Markdown インポートには「12 時間あたり約 120 ファイル」の
レート制限があるため、1 zip あたり TARGET (=100) 件程度に抑える。

主な関数:
  - group_files_by_conversation : part ファイルを元会話 stem でグループ化
  - split_into_batches          : 会話を跨がずにバッチ分割
  - file_sha1                    : 差分検出用ハッシュ
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path
from typing import Any

# Code_006 の出力ファイル名規則: {元stem}__partNN_pcpAAA-BBB.md
PART_RE = re.compile(r"^(.+?)__part\d+_pcp\d+-\d+$")


def extract_orig_stem(md_name: str) -> str:
    stem = Path(md_name).stem
    m = PART_RE.match(stem)
    return m.group(1) if m else stem


def group_files_by_conversation(
    md_files: list[Path],
) -> list[tuple[str, list[Path]]]:
    groups: dict[str, list[Path]] = {}
    for p in md_files:
        stem = extract_orig_stem(p.name)
        groups.setdefault(stem, []).append(p)
    for stem in groups:
        groups[stem].sort(key=lambda p: p.name)
    return sorted(groups.items(), key=lambda kv: kv[0])


def split_into_batches(
    grouped: list[tuple[str, list[Path]]],
    target: int = 100,
    overflow: int = 20,
) -> list[list[tuple[str, list[Path]]]]:
    """会話 (グループ) を跨がずにバッチへ詰める。"""
    batches: list[list[tuple[str, list[Path]]]] = []
    current: list[tuple[str, list[Path]]] = []
    current_count = 0
    max_files = target + overflow

    for stem, files in grouped:
        n = len(files)
        if n > max_files:
            if current:
                batches.append(current)
                current = []
                current_count = 0
            batches.append([(stem, files)])
            continue
        if current and current_count + n > max_files:
            batches.append(current)
            current = [(stem, files)]
            current_count = n
            continue
        current.append((stem, files))
        current_count += n

    if current:
        batches.append(current)
    return batches


def write_zip(
    batch: list[tuple[str, list[Path]]],
    zip_path: Path,
    compression_level: int = 6,
) -> tuple[int, int]:
    """バッチを zip 化し、(ファイル数, 元バイト合計) を返す。"""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    n_files = 0
    total_bytes = 0
    with zipfile.ZipFile(
        zip_path, "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=compression_level,
    ) as zf:
        for _, files in batch:
            for src in files:
                zf.write(src, arcname=src.name)
                n_files += 1
                try:
                    total_bytes += src.stat().st_size
                except OSError:
                    pass
    return n_files, total_bytes


def file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    h.update(path.read_bytes())
    return h.hexdigest()


def text_sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def format_size(n: int) -> str:
    n_f = float(n)
    for unit in ["B", "KB", "MB", "GB"]:
        if n_f < 1024:
            return f"{n_f:.1f} {unit}"
        n_f /= 1024
    return f"{n_f:.1f} TB"
