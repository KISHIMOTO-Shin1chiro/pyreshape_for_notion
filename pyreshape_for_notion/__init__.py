"""
pyreshape_for_notion

AI サービス (ChatGPT / Claude / Gemini) のチャットエクスポートを
Notion インポート用 Markdown に変換するためのライブラリ。

Google Drive / Google Colab 上での利用を想定。

基本的な使い方:

  # Colab で Drive をマウント
  from pyreshape_for_notion.core import drive_io
  my_drive = drive_io.mount_google_drive()

  # プラットフォームごとのパイプラインを呼ぶ
  from pyreshape_for_notion import gemini
  result = gemini.full_export(
      raw_export_dir=my_drive / "Log_Gemini/v1/0_raw_export",
      base_dir=my_drive / "Log_Gemini/v1",
  )
  print(result)

低レベル API (細かく制御したい場合):

  from pyreshape_for_notion import gemini, core
  convs = gemini.parse_folder(raw_export_dir)        # 正規化会話のリスト
  core.save_notion_md(convs, notion_dir)             # Notion MD 化
  core.split_notion_md_files(notion_dir, split_dir)  # pcp 分割
  core.make_zip_batches(split_dir, zip_dir)          # zip 化
"""

from __future__ import annotations

__version__ = "0.5.1"

from . import core
from . import chatgpt
from . import claude
from . import gemini

__all__ = ["core", "chatgpt", "claude", "gemini", "__version__"]
