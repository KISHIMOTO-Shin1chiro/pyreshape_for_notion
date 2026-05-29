# 変更履歴

このプロジェクトの主要な変更点を記録します。バージョン番号は [セマンティック バージョニング](https://semver.org/lang/ja/) に従います。

## [0.5.0] - 2026-05-29

### 修正

- Notion インポート時にファイル名が UUID 系の長い文字列で表示され、内容が判別できない問題に対処しました (pcp_021 で報告)。Notion MD を可読なファイル名 (`{YYYY-MM-DD}__{安全化タイトル}__{conv_id 先頭 8 文字}.md`) にリネームする工程を追加しました。例: `2025-12-19__悩み相談_GitHubの使い方など__abc12345.md`。

### 追加

- 新規モジュール `core/filename.py`: ファイル名生成と sanitize、rename 工程と CSV 出力を担う。`sanitize_title`、`build_readable_stem`、`rename_notion_md_files`、`update_renamed_for_convs` などを公開。
- 対応表 CSV `6_report/filename_mapping.csv` を自動生成。列は `conv_id, title, created_at, old_filename, new_filename`。UTF-8 BOM 付きで Excel 互換。
- 増分更新時に、会話名 (title) が変更された場合は古い名前のリネーム後ファイルを自動削除して新名で再生成 (混在防止)。

### 変更 (破壊的)

- フォルダ命名体系を 0.4.0 から次のように変更しました。

| 0.4.0 | 0.5.0 |
|---|---|
| `2_notion_md` | `2_notion_md` (rename 前を保持) |
| (なし) | `3_notion_md_renamed` (新規, 可読名) |
| `3_notion_md_split` | `4_notion_md_renamed_split` |
| `4_zip_batches` | `5_zip_batches` |
| `4_zip_batches_diff` | `5_zip_batches_diff` |
| (なし) | `6_report` (新規, 対応表 CSV など) |

- `core.layout.DriveLayout` の各プロパティが新フォルダを指すよう更新。
- `core.run_full_export` の戻り値に `n_renamed`, `mapping_csv` を追加。
- `core.run_incremental_export` の戻り値に `n_renamed`, `mapping_csv` を追加。

### 設計判断 (pcp_021_002 で合意)

- rename は「ファイル削除→再生成」ではなく「rename 前後を別フォルダで管理」する方式を採用。これにより旧ファイル削除に伴うリスク (誤削除、フォルダ汚染) を構造的に排除。
- `2_notion_md` には常に UUID 系名のファイルが残り、ライブラリの内部処理 (split JSON との対応付け) と後段の rename の両方の入力になる。
- 対応表 CSV は `_snapshot` (管理用) ではなく `6_report` (ユーザが目視で開く想定) に置く。

### 既存ユーザの移行手順

- 0.4.0 で生成済みの `3_notion_md_split` と `4_zip_batches` フォルダは、0.5.0 でフォルダ名が変わるため使われなくなります。手動で削除しても、放置しても安全です (新しい処理は新フォルダに出力されます)。
- 0.5.0 にアップグレード後、`full_export` をもう一度実行すると、新しい `3_notion_md_renamed`、`4_notion_md_renamed_split`、`5_zip_batches`、`6_report` が自動生成されます。Notion へは `5_zip_batches/` 内の新しい zip をインポートしてください。

## [0.4.0] - 2026-05-28

### 修正

- Notion インポートが失敗するパターンを未然に防止するようになりました。具体的には、Claude のエクスポートに含まれる思考ブロック・ツール使用の痕跡 (`This block is not supported on your current device yet.` を含むコードフェンス) と、ブロック数式 (`$$...$$`) が原因で Notion のパーサーが文書構造を解釈できずインポート全体を拒否する問題に対処しました (pcp_017 で報告)。
- 既定の挙動として、`conversation_to_notion_md` および `full_export` / `incremental_export` の出力に自動的にクリーニングが適用されます。既存ユーザは呼び出しコードを変更する必要はありません。

### 追加

- `core/notion_cleanup.py` モジュールを新設しました。Notion インポートを失敗させるノイズを除去・変換する純粋関数 `clean_for_notion(text)` を提供します。
- `conversation_to_notion_md(..., notion_safe=True)` 引数を追加しました。既定で `True` (クリーニング有効)。デバッグや無加工出力が必要な場合は `False` にできます。
- `core.clean_notion_md_folder(folder)` を追加しました。0.3.0 以前で生成済みの `2_notion_md` や `3_notion_md_split` 内のファイルを、後から一括修復できます。
- 回帰テスト `tests/test_notion_cleanup.py` (9 件) を追加しました。

### 既存の挙動への影響

- 0.3.0 以前で生成した Markdown ファイルそのものは変わりません (再生成すれば新しい出力に切り替わります)。
- pcp_017 の応急処置スクリプト `clean_md_for_notion.py` の機能は本モジュールに統合されました。今後は `from pyreshape_for_notion.core import clean_for_notion` を使ってください。

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
