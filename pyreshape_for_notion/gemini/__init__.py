"""
pyreshape_for_notion.gemini

Gemini (AI Chat Exporter) 用パイプライン。
入力は 0_raw_export フォルダ内の {YYYY-MM-DD}_{title}.md 群。

高レベル使用例:
  from pyreshape_for_notion import gemini
  gemini.full_export(
      raw_export_dir=".../Log_Gemini/v1/0_raw_export",
      base_dir=".../Log_Gemini/v1",
  )

出力フォルダ構成は pyreshape_for_notion.core.layout に従う:
  base_dir/0_raw_export, 1_split_json, 2_notion_md,
           3_notion_md_split, 4_zip_batches, 4_zip_batches_diff, _snapshot
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import parser
from ..core import run_full_export, run_incremental_export

PLATFORM = "gemini"


def parse_folder(raw_export_dir: Path) -> list:
    """0_raw_export フォルダを正規化会話のリストにする。"""
    return parser.parse_folder(Path(raw_export_dir))


def full_export(
    raw_export_dir: str | Path,
    base_dir: str | Path,
    max_pcps_per_part: int = 25,
    target: int = 100,
    overflow: int = 20,
    skip_empty: bool = True,
) -> dict[str, Any]:
    """初回投入ワークフロー一括実行。"""
    return run_full_export(
        parse_folder, raw_export_dir, base_dir,
        max_pcps_per_part=max_pcps_per_part,
        target=target, overflow=overflow, skip_empty=skip_empty,
    )


def incremental_export(
    raw_export_dir: str | Path,
    base_dir: str | Path,
    max_pcps_per_part: int = 25,
    skip_empty: bool = True,
) -> dict[str, Any]:
    """増分更新ワークフロー。"""
    return run_incremental_export(
        parse_folder, raw_export_dir, base_dir,
        max_pcps_per_part=max_pcps_per_part, skip_empty=skip_empty,
    )
