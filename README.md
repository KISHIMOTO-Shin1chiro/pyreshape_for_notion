# pyreshape_for_notion

AI サービス (ChatGPT / Claude / Gemini) のチャットエクスポートを、Notion インポート用の Markdown に変換するための Python ライブラリです。Google Drive と Google Colab 上での利用を想定しています。

現在のバージョン: 0.5.1 (変更点は [CHANGELOG.md](CHANGELOG.md) を参照)

## ライブラリ作成の動機

私は、ChatGPT, Claude, Gemini の３種の Frontier AI Services を、主に自身の調査研究に用いてきました。これらを使い続けていきますと、歳月が経つにつれ、莫大な量のテキストデータが各アカウント内に蓄積されていきます。それらのデータマネジメントを効率化し、データを利用したい場面でわかりやすく可視化されている状況をつくるためにどうすればよいかを考えた末、Notion への定期的なデータ移管が現状で最も有効であると結論付けました。Notion へのデータ移管を、当初は手動でやっていたのですが、とてつもない手間と時間がかかることに気づかされました。加えて、Notion が採用している Enhanced Markdown に則った文書の階層構造，TeX式，テーブル，コンピュータ言語によるコード類（Python, Mermaid, etc.）がそのまま保持されないことが多く、Notion 上でそれらを手動変更するのには限界があると悟りました。

## 設計の考え方

これまで `Code_000` 〜 `Code_008` として個別のスクリプトで実装してきた処理を、import して関数として呼び出せるライブラリに再構成したものです。3 プラットフォームで共通するロジック (Notion MD 化、差分検出、pcp 分割、zip バッチ化) を `pyreshape_for_notion.core` に集約し、入力フォーマットの違いを吸収するパーサだけを `pyreshape_for_notion.chatgpt` / `pyreshape_for_notion.claude` / `pyreshape_for_notion.gemini` に分離しています。

```
pyreshape_for_notion/
├── core/              共通ロジック層
│   ├── schema.py        正規化済み会話の型定義
│   ├── drive_io.py      ファイル入出力の抽象化
│   ├── layout.py        出力フォルダ命名体系の一元定義
│   ├── notion_md.py     Notion MD 変換 (旧 Code_003)
│   ├── notion_cleanup.py Notion インポート向けクリーニング (0.4.0 追加)
│   ├── filename.py       可読ファイル名 rename + 対応表 CSV (0.5.0 追加)
│   ├── diff.py          差分検出 (旧 Code_004 中核)
│   ├── pcp_split.py     pcp 単位分割 (旧 Code_006)
│   ├── zip_batch.py     zip バッチ化 (旧 Code_007/008)
│   └── pipeline.py      高レベル処理関数
├── chatgpt/           ChatGPT 固有パーサ (mapping 構造を線形化)
├── claude/            Claude 固有パーサ (chat_messages を整形)
└── gemini/            Gemini 固有パーサ (MD を解析, SHA-1 で ID 導出)
```

## Colab での使い方

### ステップ 1: ライブラリのインストール

GitHub で公開した場合、Colab のセルで次のように直接インストールできます。

```python
!pip install git+https://github.com/KISHIMOTO-Shin1chiro/pyreshape_for_notion.git
```

開発中で Drive 上にソースを置いている場合は、editable install も可能です。

```python
from google.colab import drive
drive.mount('/content/drive')
!pip install -e /content/drive/MyDrive/pyreshape_for_notion
```

### ステップ 2: Drive のマウント

```python
from pyreshape_for_notion.core import drive_io
my_drive = drive_io.mount_google_drive()   # /content/drive/MyDrive を返す
```

### ステップ 3: 高レベル API による一括処理

初回投入は `full_export` 一発で、parse → split JSON → Notion MD → pcp 分割 → zip バッチ化まで実行されます。

```python
from pyreshape_for_notion import gemini

result = gemini.full_export(
    raw_export_dir = my_drive / "Log_Gemini/v1/0_raw_export",
    base_dir       = my_drive / "Log_Gemini/v1",
)
print(result)
# {'n_conversations': 3, 'n_saved': 2, 'n_skipped': 1, 'n_zip_batches': 1, ...}
```

増分更新は `incremental_export` で、差分検出して NEW / UPDATED の会話だけを再生成します。

```python
result = gemini.incremental_export(
    raw_export_dir = my_drive / "Log_Gemini/v1/0_raw_export",
    base_dir       = my_drive / "Log_Gemini/v1",
)
print(result)
# {'n_new': 1, 'n_updated': 2, 'n_unchanged': 50, ...}
```

ChatGPT 版・Claude 版もまったく同じインターフェースです。

```python
from pyreshape_for_notion import chatgpt, claude

chatgpt.full_export(
    raw_export_dir = my_drive / "Log_ChatGPT/v3/0_raw_export",
    base_dir       = my_drive / "Log_ChatGPT/v3",
)
claude.full_export(
    raw_export_dir = my_drive / "Log_Claude/v2/0_raw_export",
    base_dir       = my_drive / "Log_Claude/v2",
)
```

### ステップ 4: 低レベル API による細かい制御

各ステップを個別に呼ぶこともできます。

```python
from pyreshape_for_notion import gemini, core
from pyreshape_for_notion.core import DriveLayout

base_dir = my_drive / "Log_Gemini/v1"
lay = DriveLayout(base_dir)

# 1. パース (正規化会話のリストを得る)
convs = gemini.parse_folder(lay.raw_export)

# 2. Notion MD 化 (UUID 系名で 2_notion_md/ に保存)
core.save_notion_md(convs, lay.notion_md)

# 3. rename (3_notion_md_renamed/ に可読名でコピー + 対応表 CSV)
core.rename_notion_md_files(
    convs,
    source_dir=lay.notion_md,
    target_dir=lay.notion_md_renamed,
    mapping_csv_path=lay.filename_mapping_csv,
)

# 4. pcp 単位分割 (rename 後の MD を分割)
core.split_notion_md_files(lay.notion_md_renamed, lay.notion_md_split,
                            max_pcps_per_part=25)

# 5. zip バッチ化
core.make_zip_batches(lay.notion_md_split, lay.zip_batches,
                       target=100, overflow=20)
```

正規化会話は 3 プラットフォームで共通のスキーマなので、`core` の関数はどのプラットフォームの `parse_folder` 出力に対しても使えます。

## 出力フォルダ構成

`base_dir` の直下に、処理の作成順に 0 始まりで連番を付したフォルダが生成されます。過度に nested にせず、すべて `base_dir` 直下のフラット構成です。

```
base_dir/
├── 0_raw_export/              入力。各サービスのエクスポートを置く
├── 1_split_json/              正規化済み JSON
├── 2_notion_md/               Notion 用 Markdown (UUID 系名、rename 前)
├── 3_notion_md_renamed/       rename 後 Markdown (可読名)        ← 0.5.0 新規
├── 4_notion_md_renamed_split/ pcp 単位分割した Markdown
├── 5_zip_batches/             初回 zip バッチ
├── 5_zip_batches_diff/        差分 zip バッチ (増分更新時)
├── 6_report/                  対応表 CSV 等の分析成果物          ← 0.5.0 新規
│   └── filename_mapping.csv
└── _snapshot/                 差分検出用スナップショット (管理用、番号なし)
```

`3_notion_md_renamed/` のファイル名は `{YYYY-MM-DD}__{安全化タイトル}__{conv_id 先頭 8 文字}.md` 形式です。例: `2025-12-19__悩み相談_GitHubの使い方など__abc12345.md`。Notion インポート後に内容を判別しやすくなります。`2_notion_md/` には rename 前の UUID 系名ファイルが残り続けます (削除されません)。

`6_report/filename_mapping.csv` には、旧ファイル名と新ファイル名、タイトル、作成日時、conv_id の対応表が記録されます。後からの追跡や Excel での確認に使えます。

フォルダ名は `pyreshape_for_notion.core.layout` に一元定義されています。変更したい場合はこのモジュールを編集してください。`DriveLayout` クラスで各パスを取得することもできます。

```python
from pyreshape_for_notion.core import DriveLayout
lay = DriveLayout(my_drive / "Log_Gemini/v1")
print(lay.notion_md)             # .../Log_Gemini/v1/2_notion_md
print(lay.notion_md_renamed)     # .../Log_Gemini/v1/3_notion_md_renamed
print(lay.filename_mapping_csv)  # .../Log_Gemini/v1/6_report/filename_mapping.csv
```

## 主要なパラメータ

`max_pcps_per_part` (既定 25): 1 つの分割ファイルに含める pcp の最大数。

`target` / `overflow` (既定 100 / 20): 1 つの zip に含めるファイル数の目安と許容超過。Notion の Markdown インポートのレート制限 (12 時間あたり約 120 ファイル) を踏まえた値です。

`skip_empty` (既定 True): 空会話 (本文がほぼ無い削除済みチャット等) を処理対象から除外するか。

`dedupe` (既定 True): 同一の prompt-completion ペアの重複を除去するか。Claude エクスポートのツリー分岐・再生成に由来する重複に対応します。

`shift_body_headings` (既定 False): 本文中の見出しレベルを 1 段繰り下げて pcp 見出しの下位に位置づけるか。既定では本文の見出しを原文のレベルのまま保持します。

`notion_safe` (既定 True, 0.4.0 で追加): Notion インポートを失敗させるパターン (Claude の思考ブロック痕跡、ブロック数式 `$$...$$`) を自動的に除去・変換します。既定で有効なので、通常は意識する必要はありません。

## Notion インポートの互換性 (0.4.0)

Claude のエクスポートには、思考ブロックやツール使用 (コード実行・ウェブ検索) の痕跡が `This block is not supported on your current device yet.` を含むコードフェンスとして書き出されています。これらが本文と入り組むと、コードフェンスの開閉境界がずれて Notion のパーサーが文書構造を解釈できず、インポート全体が失敗します。

0.4.0 では、Notion MD 生成時に自動的にこれらのノイズを除去するクリーニングが入りました。新規生成では何も意識する必要はありません。

過去 (0.3.0 以前) で生成済みの Markdown ファイルを後から修復したい場合は、次のように一括クリーニングできます。

```python
from pyreshape_for_notion.core import clean_notion_md_folder
stats = clean_notion_md_folder(base_dir / "4_notion_md_renamed_split")
print(stats)  # {'files': N, 'unsupported_removed': X, 'block_math_converted': Y}
```

## 出力される Markdown の構造

各会話は次の構造の Markdown に変換されます (v0.2.0 以降の見出しベース構造、v0.4.0 で Notion 向けクリーニング自動化)。

```markdown
# 会話タイトル

## pcp_001

**A Prompt by User**

(プロンプト本文。インデントなし)

**A Completion by LLM**

(回答本文。見出し ## や箇条書きの階層、コードブロックがそのまま保持される)

---
```

v0.1.0 では pcp を箇条書き (`- pcp_NNN`) で表現し本文を 4 スペース字下げしていましたが、これが Notion インポート時に本文中の見出しをプレーンテキスト化させ、箇条書き階層を壊す原因でした。v0.2.0 では pcp を見出し (`## pcp_NNN`) で表現し本文を字下げしないことで、この問題を解消しています。

## テスト

```bash
pip install -e ".[dev]"
pytest
```

`tests/test_smoke.py` が 3 プラットフォームの end-to-end 動作を、`tests/test_notion_md_v2.py` が見出し・階層の保持と重複除去を検証します。

## ライセンス

MIT License。個人利用を主目的としています。詳細は [LICENSE](LICENSE) を参照してください。
