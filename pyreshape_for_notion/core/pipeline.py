"""
pyreshape_for_notion.core.pipeline

正規化会話のリストを受け取り、Notion MD 化・差分更新・zip 化までを
高レベル関数として提供する。プラットフォーム非依存。

プラットフォーム固有層 (chatgpt/claude/gemini) は parse_folder() で
NormalizedConv のリストを作り、この pipeline の関数に渡すだけでよい。
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable

from . import drive_io
from .layout import DriveLayout
from .schema import NormalizedConv, is_empty_chat
from .notion_md import conversation_to_notion_md
from .diff import (
    compute_diff, build_snapshot, load_snapshot_records, conv_fingerprint,
)
from .pcp_split import split_md_text
from .zip_batch import (
    group_files_by_conversation, split_into_batches, write_zip,
    file_sha1, format_size,
)

JST = timezone(timedelta(hours=9))


def _now_iso() -> str:
    return datetime.now(JST).isoformat()


def _split_filename(conv: NormalizedConv, index: int) -> str:
    cid = conv.get("uuid") or "noid"
    return f"{index:04d}_{cid}.json"


# ============================================================
# split JSON 保存 (Code_001 後半相当)
# ============================================================
def save_split_json(
    convs: list[NormalizedConv],
    output_dir: Path,
    skip_empty: bool = True,
    empty_threshold: float = 0.95,
) -> dict[str, Any]:
    """正規化会話を個別 JSON として保存する。"""
    drive_io.ensure_dir(output_dir)
    saved: list[Path] = []
    skipped: list[NormalizedConv] = []

    for i, conv in enumerate(convs):
        if skip_empty:
            is_empty, stats = is_empty_chat(conv, threshold=empty_threshold)
            if is_empty:
                skipped.append({**conv, "_empty_stats": stats})
                continue
        path = output_dir / _split_filename(conv, i)
        drive_io.write_json(path, conv)
        saved.append(path)

    return {"saved": saved, "skipped": skipped}


# ============================================================
# Notion MD 保存 (Code_003 相当)
# ============================================================
def save_notion_md(
    convs: list[NormalizedConv],
    output_dir: Path,
    skip_empty: bool = True,
    empty_threshold: float = 0.95,
) -> list[Path]:
    drive_io.ensure_dir(output_dir)
    out_paths: list[Path] = []
    for i, conv in enumerate(convs):
        if skip_empty:
            is_empty, _ = is_empty_chat(conv, threshold=empty_threshold)
            if is_empty:
                continue
        md = conversation_to_notion_md(conv)
        stem = _split_filename(conv, i).rsplit(".", 1)[0]
        path = output_dir / f"{stem}.md"
        drive_io.write_text(path, md)
        out_paths.append(path)
    return out_paths


# ============================================================
# pcp 単位分割 (Code_006 相当)
# ============================================================
def split_notion_md_files(
    notion_md_dir: Path,
    output_dir: Path,
    max_pcps_per_part: int = 25,
) -> list[Path]:
    files = drive_io.list_files(notion_md_dir, suffix=".md")
    drive_io.ensure_dir(output_dir)
    out_paths: list[Path] = []
    for p in files:
        text = p.read_text(encoding="utf-8")
        parts = split_md_text(text, p.stem, p.name, max_pcps_per_part)
        for name, content in parts:
            op = output_dir / name
            drive_io.write_text(op, content)
            out_paths.append(op)
    return out_paths


# ============================================================
# zip バッチ化 (Code_007 相当)
# ============================================================
def make_zip_batches(
    md_split_dir: Path,
    output_dir: Path,
    target: int = 100,
    overflow: int = 20,
    compression_level: int = 6,
) -> list[dict[str, Any]]:
    files = drive_io.list_files(md_split_dir, suffix=".md")
    drive_io.ensure_dir(output_dir)
    grouped = group_files_by_conversation(files)
    batches = split_into_batches(grouped, target=target, overflow=overflow)

    infos: list[dict[str, Any]] = []
    pad = max(2, len(str(len(batches))))
    for i, batch in enumerate(batches, 1):
        n_expected = sum(len(fs) for _, fs in batch)
        zip_name = f"notion_md_batch_{i:0{pad}d}_{n_expected:03d}files.zip"
        zip_path = output_dir / zip_name
        n_files, total_bytes = write_zip(batch, zip_path, compression_level)
        infos.append({
            "zip_name": zip_name,
            "n_files": n_files,
            "n_conversations": len(batch),
            "zip_size": zip_path.stat().st_size,
            "total_bytes": total_bytes,
        })
    return infos


# ============================================================
# 差分更新 (Code_004 相当)
# ============================================================
def run_incremental_update(
    new_convs: list[NormalizedConv],
    split_dir: Path,
    notion_dir: Path,
    snapshot_path: Path,
    skip_empty: bool = True,
    empty_threshold: float = 0.95,
) -> dict[str, Any]:
    """
    new_convs を旧 snapshot と比較し、NEW/UPDATED の会話のみ
    split JSON と Notion MD を再生成する。snapshot を更新する。
    """
    import re

    if snapshot_path.exists():
        snap_obj = drive_io.read_json(snapshot_path)
        old_index = load_snapshot_records(snap_obj)
    else:
        old_index = {}

    diff = compute_diff(
        new_convs, old_index,
        skip_empty=skip_empty, empty_threshold=empty_threshold,
    )

    def _purge(conv_id: str) -> None:
        if not conv_id:
            return
        pattern = re.compile(r"^\d{4}_" + re.escape(conv_id) + r"(?:\.|$)")
        for d in (split_dir, notion_dir):
            if not d.exists():
                continue
            for p in d.iterdir():
                if pattern.match(p.name):
                    p.unlink()

    targets = diff["new"] + diff["updated"]
    targets.sort(key=lambda t: t[0])
    for i, conv in targets:
        cid = conv.get("uuid") or ""
        _purge(cid)
        drive_io.write_json(split_dir / _split_filename(conv, i), conv)
        md = conversation_to_notion_md(conv)
        stem = _split_filename(conv, i).rsplit(".", 1)[0]
        drive_io.write_text(notion_dir / f"{stem}.md", md)

    snap_obj = build_snapshot(
        new_convs, skip_empty=skip_empty,
        empty_threshold=empty_threshold, saved_at=_now_iso(),
    )
    drive_io.write_json(snapshot_path, snap_obj)

    return {
        "n_new": len(diff["new"]),
        "n_updated": len(diff["updated"]),
        "n_unchanged": len(diff["unchanged"]),
        "n_deleted": len(diff["deleted"]),
        "n_skipped_empty": len(diff["skipped_empty"]),
        "diff": diff,
    }


# ============================================================
# プラットフォーム共通の高レベルワークフロー
# ============================================================
def run_full_export(
    parser_fn: Callable[[Path], list[NormalizedConv]],
    raw_export_dir: str | Path,
    base_dir: str | Path,
    max_pcps_per_part: int = 25,
    target: int = 100,
    overflow: int = 20,
    skip_empty: bool = True,
) -> dict[str, Any]:
    """
    初回投入ワークフロー一括実行 (プラットフォーム非依存):
      parse → split JSON → Notion MD → pcp 分割 → zip バッチ化

    parser_fn: raw_export_dir を受け取り NormalizedConv のリストを返す関数。
               各プラットフォームの parse_folder を渡す。
    フォルダ構成は core.layout.DriveLayout に従う。
    """
    lay = DriveLayout(base_dir)

    convs = parser_fn(Path(raw_export_dir))
    r_split = save_split_json(convs, lay.split_json, skip_empty=skip_empty)
    save_notion_md(convs, lay.notion_md, skip_empty=skip_empty)
    split_notion_md_files(lay.notion_md, lay.notion_md_split,
                          max_pcps_per_part=max_pcps_per_part)
    infos = make_zip_batches(lay.notion_md_split, lay.zip_batches,
                             target=target, overflow=overflow)

    return {
        "n_conversations": len(convs),
        "n_saved": len(r_split["saved"]),
        "n_skipped": len(r_split["skipped"]),
        "n_zip_batches": len(infos),
        "zip_infos": infos,
    }


def run_incremental_export(
    parser_fn: Callable[[Path], list[NormalizedConv]],
    raw_export_dir: str | Path,
    base_dir: str | Path,
    max_pcps_per_part: int = 25,
    skip_empty: bool = True,
) -> dict[str, Any]:
    """
    増分更新ワークフロー (プラットフォーム非依存):
      parse → 差分検出 → NEW/UPDATED のみ split JSON + Notion MD 再生成
      → pcp 分割
    フォルダ構成は core.layout.DriveLayout に従う。
    """
    lay = DriveLayout(base_dir)

    convs = parser_fn(Path(raw_export_dir))
    result = run_incremental_update(
        convs, lay.split_json, lay.notion_md, lay.snapshot_path,
        skip_empty=skip_empty,
    )
    split_notion_md_files(lay.notion_md, lay.notion_md_split,
                          max_pcps_per_part=max_pcps_per_part)
    return result


# ============================================================
# 既存 md ファイルの Notion 向けクリーニング (0.4.0 追加)
# ============================================================
def clean_notion_md_folder(folder: str | Path) -> dict[str, Any]:
    """
    既に生成された .md ファイル群を、Notion インポート向けに後処理する。

    0.4.0 以降の新規生成では conversation_to_notion_md が自動でクリーニング
    するため不要だが、0.3.0 以前で生成した既存ファイルを修復する目的で使う。
    対象フォルダ内のすべての .md を上書きクリーニングする。

    返り値: {files, unsupported_removed, block_math_converted}
    """
    from . import drive_io
    from .notion_cleanup import clean_for_notion

    folder = Path(folder)
    if not folder.exists():
        raise FileNotFoundError(f"フォルダがありません: {folder}")

    total = {"files": 0, "unsupported_removed": 0, "block_math_converted": 0}
    for p in sorted(folder.iterdir()):
        if p.suffix != ".md":
            continue
        text = p.read_text(encoding="utf-8")
        cleaned, stats = clean_for_notion(text)
        if cleaned != text:
            p.write_text(cleaned, encoding="utf-8")
        total["files"] += 1
        total["unsupported_removed"] += stats["unsupported_removed"]
        total["block_math_converted"] += stats["block_math_converted"]
    return total
