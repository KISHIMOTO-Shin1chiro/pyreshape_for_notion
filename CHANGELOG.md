# 変更履歴

このプロジェクトの主要な変更点を記録します。バージョン番号は [セマンティック バージョニング](https://semver.org/lang/ja/) に従います。

## [0.3.0] - 2026-05-25

### 変更 (破壊的)

- ライブラリ名を `formatipy` から `pyreshape_for_notion` に変更しました。import 文は `from pyreshape_for_notion import ...` になります。
- 出力フォルダの命名体系を、作成プロセス順の 0 始まり連番・フラット構成に変更しました。
  - `conversations_split` → `1_split_json`
  - `conversations_notion_md` → `2_notion_md`
  - `conversations_notion_md_split` → `3_notion_md_split`
  - `_archives/notion_md_zip_batches` → `4_zip_batches` (nested を解消)
  - 差分 zip → `4_zip_batches_diff`
  - 入力フォルダの推奨名を `raw_export` から `0_raw_export` に変更
  - `_snapshot` は管理用データのため番号を付けず据え置き

### 追加

- `core.layout` モジュールと `core.DriveLayout` クラスを追加し、フォルダ命名体系を一元管理できるようにしました。
- `core.run_full_export` / `core.run_incremental_export`: プラットフォーム非依存の共通ワークフロー関数。各プラットフォームの `full_export` / `incremental_export` はこれに委譲する薄いラッパになりました (重複コードの解消)。

## [0.2.0] - 2026-05-23

### 修正

- Notion インポート時に本文中の見出し (`##`, `###` 等) がプレーンテキスト化していた問題を修正しました。pcp 構造を箇条書きのインデントから Markdown 見出し (`## pcp_NNN`) に変更し、本文を一切インデントしないようにしました。
- 見出しが認識されないことに伴って本文の箇条書き階層が崩れていた問題を、上記の変更により併せて解消しました。
- completion 本文に同一の prompt-completion ペアが重複して出力されることがある問題を修正しました。`dedupe_pcps` による重複除去を既定で有効にしました。

### 追加

- `core.notion_md.shift_headings`: 本文中の見出しレベルを繰り下げるオプション機能。`conversation_to_notion_md(..., shift_body_headings=True)` で有効化できます。
- `core.notion_md.dedupe_pcps`: 同一ペアの重複除去。`conversation_to_notion_md(..., dedupe=True)` で制御できます (既定で有効)。
- pcp_016 で報告された 3 つの不具合に対する回帰テスト (`tests/test_notion_md_v2.py`, 8 件) を追加しました。

### 変更

- `core.pcp_split.PCP_LINE_RE`: 新しい見出し形式 `## pcp_NNN` と旧来の箇条書き形式 `- pcp_NNN` の両方を pcp 境界として認識するようにしました (後方互換)。

## [0.1.0] - 2026-05-23

### 追加

- 初版。ChatGPT / Claude / Gemini のチャットエクスポートを Notion インポート用 Markdown に変換するライブラリ。
- 共通ロジック層 `formatipy.core` (正規化スキーマ、Notion MD 変換、差分検出、pcp 分割、zip バッチ化、高レベルパイプライン)。
- プラットフォーム別パーサ `formatipy.chatgpt` / `formatipy.claude` / `formatipy.gemini`。
- 高レベル API `full_export` / `incremental_export`。
- スモークテスト (`tests/test_smoke.py`, 4 件)。
