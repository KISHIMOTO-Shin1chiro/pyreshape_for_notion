r"""
pyreshape_for_notion.core.filename

UUID 系名の Notion MD を可読名にリネームするモジュール (0.5.0 追加)。

ファイル名形式:
  {YYYY-MM-DD}__{安全化タイトル}__{conv_id 先頭 8 文字}.md

例:
  2025-12-19__悩み相談_GitHubの使い方など__a1b2c3d4.md
  2026-05-29__★【最重要】調査_メモ__b3c4d5e6.md

設計方針 (pcp_021_001 で合意):
  - タイトルは name フィールドをそのまま使う (正規化は行わない)
  - 日本語、絵文字、記号 (★【】●) は基本的に保持
  - OS/Drive がファイル名に使えない文字 (/ \ : * ? " < > |) と
    制御文字だけを '_' に置換
  - 連続する '_' は 1 つに圧縮
  - タイトル部分は最大 80 文字で切詰
  - conv_id 先頭 8 文字を末尾に付け、衝突を予防しつつ追跡性を保つ

工程位置 (pcp_021_002 で合意):
  入力 : 2_notion_md/        (UUID 系名のまま)
  出力 : 3_notion_md_renamed/ (可読名)
  対応表: 6_report/filename_mapping.csv
"""

from __future__ import annotations

import csv
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from . import drive_io

# OS/Drive がファイル名に使えない文字 (Windows/macOS/Linux/Google Drive 共通)
_FORBIDDEN_CHARS_RE = re.compile(r'[/\\:*?"<>|]')
_CONTROL_CHARS_RE = re.compile(r'[\x00-\x1f\x7f]')
_REPEAT_UNDERSCORE_RE = re.compile(r'_+')
_TRAILING_BAD_RE = re.compile(r'[\s.]+$')

MAX_TITLE_LEN = 80

# 旧 0.4.0 以前のファイル名: NNNN_<uuid>(.md)
_LEGACY_RE = re.compile(r'^\d{4}_[0-9a-f\-]{8,}$')

# CSV 列定義
CSV_FIELDS = ["conv_id", "title", "created_at",
              "old_filename", "new_filename"]


# ============================================================
# 文字列加工ユーティリティ
# ============================================================
def sanitize_title(title: str, max_len: int = MAX_TITLE_LEN) -> str:
    """タイトル文字列をファイル名として安全な形に整える。"""
    if not title:
        return "untitled"

    t = unicodedata.normalize("NFC", title)
    t = _FORBIDDEN_CHARS_RE.sub("_", t)
    t = _CONTROL_CHARS_RE.sub("_", t)
    t = re.sub(r"\s+", "_", t)
    t = _REPEAT_UNDERSCORE_RE.sub("_", t)
    t = _TRAILING_BAD_RE.sub("", t)
    t = t.strip("_")

    if len(t) > max_len:
        t = t[:max_len].rstrip("_")

    return t or "untitled"


def extract_date_prefix(conv: dict[str, Any]) -> str:
    """正規化会話から YYYY-MM-DD 形式の日付プレフィックスを取り出す。"""
    src = conv.get("_source") or {}
    orig = src.get("original_filename") or ""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", orig)
    if m:
        return m.group(1)

    for key in ("created_at", "updated_at"):
        v = conv.get(key) or ""
        if isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}", v):
            return v[:10]
        if isinstance(v, (int, float)) and v > 0:
            try:
                from datetime import timezone
                return datetime.fromtimestamp(v, tz=timezone.utc).strftime("%Y-%m-%d")
            except (ValueError, OSError, OverflowError):
                pass

    return "undated"


def short_conv_id(conv_id: str, length: int = 8) -> str:
    """conv_id の先頭 length 文字を返す (ファイル名衝突予防と追跡性のため)。"""
    if not conv_id:
        return "noid"
    parts = conv_id.split("-")
    cleaned = parts[0] if parts and len(parts[0]) >= length else conv_id.replace("-", "")
    return cleaned[:length] if cleaned else "noid"


def build_readable_stem(conv: dict[str, Any]) -> str:
    """1 会話分の「拡張子なしファイル名」を生成する。"""
    date_part = extract_date_prefix(conv)
    title_part = sanitize_title(conv.get("name") or "")
    conv_id = conv.get("uuid") or ""
    id_part = short_conv_id(conv_id)
    return f"{date_part}__{title_part}__{id_part}"


def build_readable_filename(conv: dict[str, Any]) -> str:
    """拡張子 .md を含む可読ファイル名。"""
    return build_readable_stem(conv) + ".md"


def is_legacy_filename(name: str) -> bool:
    """旧 0.4.0 以前のファイル名か判定する。"""
    stem = Path(name).stem
    return bool(_LEGACY_RE.match(stem))


# ============================================================
# rename 工程 (2_notion_md → 3_notion_md_renamed + 6_report/CSV)
# ============================================================
def rename_notion_md_files(
    convs: list[dict[str, Any]],
    source_dir: Path,
    target_dir: Path,
    mapping_csv_path: Path,
    skip_empty: bool = True,
    empty_threshold: float = 0.95,
) -> dict[str, Any]:
    """
    2_notion_md/ にある UUID 系名の MD を、3_notion_md_renamed/ に可読名で
    コピーする。同時に対応表 CSV を 6_report/filename_mapping.csv に書き出す。

    引数:
      convs            : 正規化会話のリスト (順序が source_dir のファイル名と一致)
      source_dir       : 2_notion_md/
      target_dir       : 3_notion_md_renamed/
      mapping_csv_path : 6_report/filename_mapping.csv

    返り値: {
      "renamed"      : リネームしたペア (旧名, 新名) のリスト,
      "skipped"      : スキップした会話のリスト,
      "collisions"   : 衝突解消した件数,
      "mapping_csv"  : 出力した CSV のパス,
    }
    """
    from .schema import is_empty_chat

    drive_io.ensure_dir(target_dir)
    drive_io.ensure_dir(mapping_csv_path.parent)

    # source_dir のファイル名規則: {index:04d}_{uuid}.md (0.4.0 形式)
    # convs[i] に対応する旧名を生成
    def _old_stem(i: int, conv: dict[str, Any]) -> str:
        cid = conv.get("uuid") or "noid"
        return f"{i:04d}_{cid}"

    renamed: list[tuple[str, str]] = []
    skipped: list[dict[str, Any]] = []
    collisions = 0
    used_stems: dict[str, str] = {}  # new_stem -> conv_id (衝突検出用)

    csv_rows: list[dict[str, str]] = []

    for i, conv in enumerate(convs):
        if skip_empty:
            is_empty, _ = is_empty_chat(conv, threshold=empty_threshold)
            if is_empty:
                skipped.append(conv)
                continue

        old_stem = _old_stem(i, conv)
        old_path = source_dir / f"{old_stem}.md"
        if not old_path.exists():
            # 2_notion_md に対応ファイルが無い場合はスキップ
            # (空会話で save_notion_md がスキップした等)
            continue

        new_stem = build_readable_stem(conv)
        # 衝突回避: 同 stem が既に使われていたら _2, _3 ... を末尾に付ける
        # (通常は conv_id 8 文字を末尾に含むため衝突は起きないが、念のため)
        final_stem = new_stem
        n = 2
        while final_stem in used_stems and used_stems[final_stem] != conv.get("uuid"):
            final_stem = f"{new_stem}_{n}"
            n += 1
            collisions += 1
        used_stems[final_stem] = conv.get("uuid") or ""

        new_path = target_dir / f"{final_stem}.md"
        # コピー (read → write で改行コード等の意図しない変換を防ぐ)
        new_path.write_bytes(old_path.read_bytes())

        renamed.append((old_path.name, new_path.name))
        csv_rows.append({
            "conv_id": conv.get("uuid") or "",
            "title": conv.get("name") or "",
            "created_at": conv.get("created_at") or "",
            "old_filename": old_path.name,
            "new_filename": new_path.name,
        })

    # CSV 出力 (UTF-8 BOM 付きで Excel 互換)
    with open(mapping_csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in csv_rows:
            writer.writerow(row)

    return {
        "renamed": renamed,
        "skipped": skipped,
        "collisions": collisions,
        "mapping_csv": mapping_csv_path,
    }


# ============================================================
# 増分更新時の rename (差分のみ処理, 旧ファイル除去)
# ============================================================
def update_renamed_for_convs(
    changed_convs: list[tuple[int, dict[str, Any]]],
    all_convs: list[dict[str, Any]],
    source_dir: Path,
    target_dir: Path,
    mapping_csv_path: Path,
) -> dict[str, Any]:
    """
    増分更新時、変更があった会話 (NEW/UPDATED) について、
    3_notion_md_renamed/ の該当ファイルだけを再生成し、
    対応表 CSV を更新する。

    旧ファイル名のクリーンアップ: 同じ conv_id の先頭 8 文字を末尾に含む
    既存ファイルを target_dir から削除してから新ファイルを書く。これにより
    会話の name が変更されても 3_notion_md_renamed 内に旧名・新名が
    混在することを防ぐ。
    """
    drive_io.ensure_dir(target_dir)
    drive_io.ensure_dir(mapping_csv_path.parent)

    # 既存 CSV を読み込み、conv_id をキーに辞書化
    existing_rows: dict[str, dict[str, str]] = {}
    if mapping_csv_path.exists():
        with open(mapping_csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cid = row.get("conv_id") or ""
                if cid:
                    existing_rows[cid] = row

    def _old_stem(i: int, conv: dict[str, Any]) -> str:
        cid = conv.get("uuid") or "noid"
        return f"{i:04d}_{cid}"

    renamed_now: list[tuple[str, str]] = []

    for i, conv in changed_convs:
        cid = conv.get("uuid") or ""
        if not cid:
            continue

        # 該当 conv_id 先頭 8 文字を末尾に含む既存ファイルを削除
        id_short = short_conv_id(cid)
        for p in list(target_dir.glob(f"*__{id_short}.md")):
            p.unlink()

        # 2_notion_md 側の対応ファイルをコピー
        old_path = source_dir / f"{_old_stem(i, conv)}.md"
        if not old_path.exists():
            continue
        new_stem = build_readable_stem(conv)
        new_path = target_dir / f"{new_stem}.md"
        new_path.write_bytes(old_path.read_bytes())
        renamed_now.append((old_path.name, new_path.name))

        # CSV 行を更新
        existing_rows[cid] = {
            "conv_id": cid,
            "title": conv.get("name") or "",
            "created_at": conv.get("created_at") or "",
            "old_filename": old_path.name,
            "new_filename": new_path.name,
        }

    # 全 conv の現在の状態を CSV に書き戻す
    # (削除された会話の行はそのまま残る - 過去履歴として有用)
    with open(mapping_csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        # all_convs 順で書き出し、CSV にあるが all_convs に無い古い行も末尾に残す
        seen = set()
        for conv in all_convs:
            cid = conv.get("uuid") or ""
            if cid in existing_rows:
                writer.writerow(existing_rows[cid])
                seen.add(cid)
        for cid, row in existing_rows.items():
            if cid not in seen:
                writer.writerow(row)

    return {
        "renamed": renamed_now,
        "mapping_csv": mapping_csv_path,
    }
