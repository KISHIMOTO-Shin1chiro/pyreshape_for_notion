"""
pyreshape_for_notion.core.layout

base_dir 配下のフォルダ命名体系を一元定義する。

命名方針 (pcp_021_002 で改訂、0.5.0):
  - 作成プロセス順に 0 始まりで連番を付す
  - 過度に nested にしない (すべて base_dir 直下のフラット構成)
  - 各工程が独立した出力フォルダを持つ (rename 前後を別フォルダに分離)
  - 処理成果物ではない管理用データ (_snapshot) は番号を付けない

フォルダ構成 (0.5.0):
  base_dir/
  ├── 0_raw_export/              入力。各サービスのエクスポート
  ├── 1_split_json/              正規化済み JSON
  ├── 2_notion_md/               Notion MD (UUID 系名のまま, rename 前)
  ├── 3_notion_md_renamed/       可読名にリネームした MD (0.5.0 新規)
  ├── 4_notion_md_renamed_split/ pcp 単位分割
  ├── 5_zip_batches/             初回 zip バッチ
  ├── 5_zip_batches_diff/        差分 zip バッチ (増分更新時)
  ├── 6_report/                  対応表 CSV 等の分析成果物 (0.5.0 新規)
  └── _snapshot/                 差分検出用スナップショット (管理用、番号なし)

0.4.0 からの変更点 (破壊的):
  - rename 工程が追加され、その入出力が新フォルダに分かれる
  - 旧: 3_notion_md_split, 4_zip_batches, 4_zip_batches_diff
  - 新: 4_notion_md_renamed_split, 5_zip_batches, 5_zip_batches_diff

フォルダ名を変更したい場合はこのモジュールだけを書き換えればよい。
"""

from __future__ import annotations

from pathlib import Path

# フォルダ名 (base_dir 直下)
RAW_EXPORT             = "0_raw_export"
SPLIT_JSON             = "1_split_json"
NOTION_MD              = "2_notion_md"
NOTION_MD_RENAMED      = "3_notion_md_renamed"       # 0.5.0 新規
NOTION_MD_RENAMED_SPLIT = "4_notion_md_renamed_split" # 0.5.0 で番号変更
ZIP_BATCHES            = "5_zip_batches"              # 0.5.0 で番号変更
ZIP_BATCHES_DIFF       = "5_zip_batches_diff"         # 0.5.0 で番号変更
REPORT                 = "6_report"                   # 0.5.0 新規
SNAPSHOT               = "_snapshot"

SNAPSHOT_FILENAME = "snapshot.json"
FILENAME_MAPPING_CSV = "filename_mapping.csv"


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
        """rename 前の Notion MD (UUID 系名)。"""
        return self.base / NOTION_MD

    @property
    def notion_md_renamed(self) -> Path:
        """rename 後の Notion MD (可読名)。0.5.0 で新設。"""
        return self.base / NOTION_MD_RENAMED

    @property
    def notion_md_split(self) -> Path:
        """pcp 単位分割の出力先 (rename 後の MD を分割)。"""
        return self.base / NOTION_MD_RENAMED_SPLIT

    # 後方互換: 0.4.0 までの notion_md_split を踏襲する別名
    @property
    def notion_md_renamed_split(self) -> Path:
        return self.base / NOTION_MD_RENAMED_SPLIT

    @property
    def zip_batches(self) -> Path:
        return self.base / ZIP_BATCHES

    @property
    def zip_batches_diff(self) -> Path:
        return self.base / ZIP_BATCHES_DIFF

    @property
    def report(self) -> Path:
        """対応表 CSV 等の分析成果物の置き場所。0.5.0 で新設。"""
        return self.base / REPORT

    @property
    def filename_mapping_csv(self) -> Path:
        """ファイル名対応表 CSV のパス。"""
        return self.base / REPORT / FILENAME_MAPPING_CSV

    @property
    def snapshot_dir(self) -> Path:
        return self.base / SNAPSHOT

    @property
    def snapshot_path(self) -> Path:
        return self.base / SNAPSHOT / SNAPSHOT_FILENAME
