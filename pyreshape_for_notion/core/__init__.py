"""
pyreshape_for_notion.core

3 プラットフォーム共通の処理ロジック層。
プラットフォーム固有のパーサ (chatgpt/claude/gemini) が出力する
正規化済み会話 (NormalizedConv) を入力として、Notion MD 化、差分検出、
pcp 分割、zip バッチ化などを行う。
"""

from .schema import (
    NormalizedConv,
    NormalizedMessage,
    make_message,
    make_conversation,
    extract_visible_text,
    is_message_empty,
    is_empty_chat,
)
from .notion_md import (
    conversation_to_notion_md,
    extract_pcp_label,
    pair_into_pcps,
)
from .diff import (
    conv_fingerprint,
    compute_diff,
    build_snapshot,
    load_snapshot_records,
)
from .pcp_split import (
    split_md_text,
    parse_md,
)
from .zip_batch import (
    group_files_by_conversation,
    split_into_batches,
    write_zip,
    file_sha1,
    text_sha1,
    format_size,
    extract_orig_stem,
)
from . import drive_io
from . import layout
from . import notion_cleanup
from . import filename
from .notion_cleanup import clean_for_notion
from .filename import (
    sanitize_title,
    build_readable_stem,
    build_readable_filename,
    rename_notion_md_files,
    update_renamed_for_convs,
    is_legacy_filename,
)
from .layout import DriveLayout
from .pipeline import (
    save_split_json,
    save_notion_md,
    split_notion_md_files,
    make_zip_batches,
    run_incremental_update,
    run_full_export,
    run_incremental_export,
    clean_notion_md_folder,
)

__all__ = [
    "save_split_json", "save_notion_md", "split_notion_md_files",
    "make_zip_batches", "run_incremental_update",
    "run_full_export", "run_incremental_export",
    "clean_notion_md_folder",
    "NormalizedConv", "NormalizedMessage",
    "make_message", "make_conversation",
    "extract_visible_text", "is_message_empty", "is_empty_chat",
    "conversation_to_notion_md", "extract_pcp_label", "pair_into_pcps",
    "conv_fingerprint", "compute_diff", "build_snapshot",
    "load_snapshot_records",
    "split_md_text", "parse_md",
    "group_files_by_conversation", "split_into_batches", "write_zip",
    "file_sha1", "text_sha1", "format_size", "extract_orig_stem",
    "drive_io",
    "layout",
    "DriveLayout",
    "notion_cleanup",
    "clean_for_notion",
    "filename",
    "sanitize_title",
    "build_readable_stem",
    "build_readable_filename",
    "rename_notion_md_files",
    "update_renamed_for_convs",
    "is_legacy_filename",
]
