"""
pyreshape_for_notion.core.layout

base_dir 配下のフォルダ命名体系を一元定義する。

命名方針 (pcp_016_003):
  - 作成プロセス順に 0 始まりで連番を付す
  - 過度に nested にしない (すべて base_dir 直下のフラット構成)
  - 処理成果物ではない管理用データ (_snapshot) は番号を付けない

フォルダ構成:
  base_dir/
  ├── 0_raw_export/          入力。各サービスのエクスポート
  ├── 1_split_json/          正規化済み JSON (旧 conversations_split)
  ├── 2_notion_md/           Notion 用 Markdown (旧 conversations_notion_md)
  ├── 3_notion_md_split/     pcp 単位分割 (旧 conversations_notion_md_split)
  ├── 4_zip_batches/         初回 zip バッチ (旧 _archives/notion_md_zip_batches)
  ├── 4_zip_batches_diff/    差分 zip バッチ (旧 _archives/notion_md_zip_batches_diff)
  └── _snapshot/             差分検出用スナップショット (番号なし)

フォルダ名を変更したい場合はこのモジュールだけを書き換えればよい。
"""

from __future__ import annotations

from pathlib import Path

# フォルダ名 (base_dir 直下)
RAW_EXPORT       = "0_raw_export"
SPLIT_JSON       = "1_split_json"
NOTION_MD        = "2_notion_md"
NOTION_MD_SPLIT  = "3_notion_md_split"
ZIP_BATCHES      = "4_zip_batches"
ZIP_BATCHES_DIFF = "4_zip_batches_diff"
SNAPSHOT         = "_snapshot"

SNAPSHOT_FILENAME = "snapshot.json"


class DriveLayout:
    """base_dir を起点に各処理フォルダの Path を提供する。"""

    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir)

    @property
    def raw_export(self) -> Path:
        return self.base / RAW_EXPORT

    @property
    def split_json(self) -> Path:
        return self.base / SPLIT_JSON

    @property
    def notion_md(self) -> Path:
        return self.base / NOTION_MD

    @property
    def notion_md_split(self) -> Path:
        return self.base / NOTION_MD_SPLIT

    @property
    def zip_batches(self) -> Path:
        return self.base / ZIP_BATCHES

    @property
    def zip_batches_diff(self) -> Path:
        return self.base / ZIP_BATCHES_DIFF

    @property
    def snapshot_dir(self) -> Path:
        return self.base / SNAPSHOT

    @property
    def snapshot_path(self) -> Path:
        return self.base / SNAPSHOT / SNAPSHOT_FILENAME
