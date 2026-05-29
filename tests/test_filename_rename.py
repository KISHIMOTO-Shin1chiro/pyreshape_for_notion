"""
0.5.0 で導入したファイル名 rename 機能の回帰テスト (pcp_021 対応)。

検証する内容:
  - sanitize_title: 禁止文字置換、日本語/絵文字/記号の保持、長さ制限
  - build_readable_stem: 日付・タイトル・conv_id の組み立て
  - rename_notion_md_files: 2_notion_md → 3_notion_md_renamed + CSV
  - update_renamed_for_convs: 増分時の旧名削除と CSV 更新
  - 新フォルダ構成 (0_raw_export ... 6_report) の DriveLayout
"""

import csv
import json
import shutil
from pathlib import Path

import pytest

from pyreshape_for_notion.core import (
    DriveLayout, sanitize_title, build_readable_stem,
    build_readable_filename, is_legacy_filename,
)
from pyreshape_for_notion.core.filename import (
    extract_date_prefix, short_conv_id,
    rename_notion_md_files, update_renamed_for_convs,
)


# ============================================================
# sanitize_title
# ============================================================
def test_sanitize_basic():
    """基本的な文字列はそのまま、空白は _ に。"""
    assert sanitize_title("hello world") == "hello_world"
    assert sanitize_title("日本語タイトル") == "日本語タイトル"


def test_sanitize_forbidden_chars():
    """OS 禁止文字 / \\ : * ? \" < > | は _ に置換。"""
    assert sanitize_title("a/b") == "a_b"
    assert sanitize_title("a:b*c?d") == "a_b_c_d"
    assert sanitize_title('a"b<c>d|e') == "a_b_c_d_e"


def test_sanitize_preserves_symbols():
    """日本語の記号 ★【】● は保持される。"""
    t = sanitize_title("★【最重要】●設計メモ")
    assert "★" in t and "【" in t and "】" in t and "●" in t


def test_sanitize_collapses_underscores():
    """連続する _ は 1 つに圧縮される。"""
    assert sanitize_title("a   b") == "a_b"
    assert sanitize_title("a___b") == "a_b"


def test_sanitize_empty_returns_untitled():
    """空文字列や None は 'untitled' に。"""
    assert sanitize_title("") == "untitled"
    assert sanitize_title(None) == "untitled"


def test_sanitize_max_length():
    """80 文字を超えるタイトルは切詰。"""
    long_title = "a" * 200
    result = sanitize_title(long_title, max_len=80)
    assert len(result) == 80


def test_sanitize_trailing_dots_removed():
    """末尾のドット・空白は除去 (Windows 制約)。"""
    assert sanitize_title("title...") == "title"
    assert sanitize_title("title   ") == "title"


# ============================================================
# extract_date_prefix
# ============================================================
def test_extract_date_from_original_filename():
    """Gemini 由来の original_filename を優先。"""
    conv = {"_source": {"original_filename": "2025-12-19_title.md"},
            "created_at": "2024-01-01T00:00:00Z"}
    assert extract_date_prefix(conv) == "2025-12-19"


def test_extract_date_from_created_at():
    """ISO 文字列 created_at から先頭 10 文字。"""
    conv = {"created_at": "2025-12-19T15:00:00+09:00"}
    assert extract_date_prefix(conv) == "2025-12-19"


def test_extract_date_from_unix_seconds():
    """UNIX 秒 created_at からも取得。"""
    conv = {"created_at": 1734588000.0}  # 2024-12-19 UTC
    result = extract_date_prefix(conv)
    assert result.startswith("2024-12-")


def test_extract_date_fallback_undated():
    """日付情報なしは 'undated'。"""
    conv = {"name": "X"}
    assert extract_date_prefix(conv) == "undated"


# ============================================================
# short_conv_id
# ============================================================
def test_short_conv_id_uuid_format():
    """UUID 形式は最初のセグメントから 8 文字。"""
    assert short_conv_id("abc12345-def6-7890-abcd-1234567890ab") == "abc12345"


def test_short_conv_id_short_first_segment():
    """先頭セグメントが短い場合はハイフン除去後の先頭 8 文字。"""
    assert short_conv_id("ab-cdefgh-12345") == "abcdefgh"


def test_short_conv_id_empty():
    assert short_conv_id("") == "noid"


# ============================================================
# build_readable_stem / filename
# ============================================================
def test_build_readable_stem():
    conv = {
        "uuid": "abc12345-def6-7890-abcd-1234567890ab",
        "name": "悩み相談_GitHubの使い方など",
        "created_at": "2025-12-19T15:00:00+09:00",
    }
    stem = build_readable_stem(conv)
    assert stem == "2025-12-19__悩み相談_GitHubの使い方など__abc12345"
    assert build_readable_filename(conv) == stem + ".md"


def test_build_readable_stem_with_symbols():
    """記号付きタイトルが保持される。"""
    conv = {
        "uuid": "b3c4d5e6-7890-abcd-ef12-345678901234",
        "name": "★【最重要】調査メモ",
        "created_at": "2026-05-29T10:00:00+09:00",
    }
    stem = build_readable_stem(conv)
    assert "★【最重要】調査メモ" in stem
    assert stem.endswith("__b3c4d5e6")


# ============================================================
# is_legacy_filename
# ============================================================
def test_is_legacy_recognizes_old_format():
    assert is_legacy_filename("0011_464369a4-8cde-4777-978a-4542d9714dee.md")
    assert is_legacy_filename("0000_abc12345def6.md")


def test_is_legacy_rejects_new_format():
    assert not is_legacy_filename(
        "2025-12-19__悩み相談_GitHubの使い方など__abc12345.md")


# ============================================================
# DriveLayout (新フォルダ構成)
# ============================================================
def test_drive_layout_new_folders():
    lay = DriveLayout("/tmp/X")
    assert lay.raw_export.name == "0_raw_export"
    assert lay.split_json.name == "1_split_json"
    assert lay.notion_md.name == "2_notion_md"
    assert lay.notion_md_renamed.name == "3_notion_md_renamed"
    assert lay.notion_md_split.name == "4_notion_md_renamed_split"
    assert lay.zip_batches.name == "5_zip_batches"
    assert lay.zip_batches_diff.name == "5_zip_batches_diff"
    assert lay.report.name == "6_report"
    assert lay.filename_mapping_csv.name == "filename_mapping.csv"
    assert lay.filename_mapping_csv.parent.name == "6_report"


# ============================================================
# rename_notion_md_files (統合)
# ============================================================
def test_rename_creates_readable_files_and_csv(tmp_path):
    """rename 工程で 3_notion_md_renamed と CSV が作られる。"""
    lay = DriveLayout(tmp_path)
    lay.notion_md.mkdir(parents=True)

    convs = [
        {"uuid": "abc12345-1111-2222-3333-444444444444",
         "name": "テスト会話A",
         "created_at": "2025-12-19T10:00:00+09:00",
         "chat_messages": [
             {"sender": "human", "index": 0, "text": "q"},
             {"sender": "assistant", "index": 1, "text": "a"},
         ]},
    ]
    # 旧名で 2_notion_md にダミーファイルを置く
    (lay.notion_md / "0000_abc12345-1111-2222-3333-444444444444.md").write_text(
        "# テスト会話A\n本文", encoding="utf-8")

    result = rename_notion_md_files(
        convs,
        source_dir=lay.notion_md,
        target_dir=lay.notion_md_renamed,
        mapping_csv_path=lay.filename_mapping_csv,
    )

    # 新名ファイルができている
    new_files = list(lay.notion_md_renamed.glob("*.md"))
    assert len(new_files) == 1
    assert new_files[0].name == "2025-12-19__テスト会話A__abc12345.md"

    # CSV に行がある
    with open(lay.filename_mapping_csv, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["title"] == "テスト会話A"
    assert rows[0]["new_filename"] == "2025-12-19__テスト会話A__abc12345.md"


def test_rename_preserves_original_in_2_notion_md(tmp_path):
    """rename 後も 2_notion_md/ には旧名ファイルが残る (コピー動作)。"""
    lay = DriveLayout(tmp_path)
    lay.notion_md.mkdir(parents=True)

    convs = [
        {"uuid": "a-1-2-3-4", "name": "T",
         "created_at": "2025-01-01T00:00:00Z",
         "chat_messages": [{"sender": "human", "index": 0, "text": "q"}]},
    ]
    old_path = lay.notion_md / "0000_a-1-2-3-4.md"
    old_path.write_text("# T\n", encoding="utf-8")

    rename_notion_md_files(
        convs,
        source_dir=lay.notion_md,
        target_dir=lay.notion_md_renamed,
        mapping_csv_path=lay.filename_mapping_csv,
    )

    assert old_path.exists(), "rename は旧ファイルを保持する (コピー動作)"


# ============================================================
# update_renamed_for_convs (増分更新時の旧名削除)
# ============================================================
def test_update_removes_stale_name_on_title_change(tmp_path):
    """会話名が変わったとき、3_notion_md_renamed の旧名ファイルが削除される。"""
    lay = DriveLayout(tmp_path)
    lay.notion_md.mkdir(parents=True)
    lay.notion_md_renamed.mkdir(parents=True)
    lay.filename_mapping_csv.parent.mkdir(parents=True)

    # 初期状態: 旧タイトル名のファイルが 3_notion_md_renamed にある
    old_renamed = lay.notion_md_renamed / "2025-12-19__旧タイトル__abc12345.md"
    old_renamed.write_text("旧内容", encoding="utf-8")

    # 2_notion_md にも対応ファイル
    conv_id = "abc12345-1111-2222-3333-444444444444"
    (lay.notion_md / f"0000_{conv_id}.md").write_text("新内容", encoding="utf-8")

    convs = [
        {"uuid": conv_id, "name": "新タイトル",
         "created_at": "2025-12-19T10:00:00+09:00",
         "chat_messages": [{"sender": "human", "index": 0, "text": "q"}]},
    ]

    update_renamed_for_convs(
        changed_convs=[(0, convs[0])],
        all_convs=convs,
        source_dir=lay.notion_md,
        target_dir=lay.notion_md_renamed,
        mapping_csv_path=lay.filename_mapping_csv,
    )

    # 旧名は消え、新名だけがある
    files = sorted(p.name for p in lay.notion_md_renamed.glob("*.md"))
    assert files == ["2025-12-19__新タイトル__abc12345.md"]
