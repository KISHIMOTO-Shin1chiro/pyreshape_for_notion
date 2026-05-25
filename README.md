# pyreshape\_for\_notion

AI サービス (ChatGPT / Claude / Gemini) のチャットエクスポートを、Notion インポート用の Markdown に変換するための Python ライブラリです。Google Drive と Google Colab 上での利用を想定しています。

現在のバージョン: 0.3.0 (変更点は [CHANGELOG.md](CHANGELOG.md) を参照)

## 設計の考え方

これまで `Code\_000` 〜 `Code\_008` として個別のスクリプトで実装してきた処理を、import して関数として呼び出せるライブラリに再構成したものです。3 プラットフォームで共通するロジック (Notion MD 化、差分検出、pcp 分割、zip バッチ化) を `pyreshape\_for\_notion.core` に集約し、入力フォーマットの違いを吸収するパーサだけを `pyreshape\_for\_notion.chatgpt` / `pyreshape\_for\_notion.claude` / `pyreshape\_for\_notion.gemini` に分離しています。

```
pyreshape\_for\_notion/
├── core/              共通ロジック層
│   ├── schema.py        正規化済み会話の型定義
│   ├── drive\_io.py      ファイル入出力の抽象化
│   ├── layout.py        出力フォルダ命名体系の一元定義
│   ├── notion\_md.py     Notion MD 変換 (旧 Code\_003)
│   ├── diff.py          差分検出 (旧 Code\_004 中核)
│   ├── pcp\_split.py     pcp 単位分割 (旧 Code\_006)
│   ├── zip\_batch.py     zip バッチ化 (旧 Code\_007/008)
│   └── pipeline.py      高レベル処理関数
├── chatgpt/           ChatGPT 固有パーサ (mapping 構造を線形化)
├── claude/            Claude 固有パーサ (chat\_messages を整形)
└── gemini/            Gemini 固有パーサ (MD を解析, SHA-1 で ID 導出)
```

## Colab での使い方

### ステップ 1: ライブラリのインストール

GitHub で公開した場合、Colab のセルで次のように直接インストールできます。

```python
!pip install git+https://github.com/KISHIMOTO-Shin1chiro/pyreshape\_for\_notion.git
```

開発中で Drive 上にソースを置いている場合は、editable install も可能です。

```python
from google.colab import drive
drive.mount('/content/drive')
!pip install -e /content/drive/MyDrive/pyreshape\_for\_notion
```

### ステップ 2: Drive のマウント

```python
from pyreshape\_for\_notion.core import drive\_io
my\_drive = drive\_io.mount\_google\_drive()   # /content/drive/MyDrive を返す
```

### ステップ 3: 高レベル API による一括処理

初回投入は `full\_export` 一発で、parse → split JSON → Notion MD → pcp 分割 → zip バッチ化まで実行されます。

```python
from pyreshape\_for\_notion import gemini

result = gemini.full\_export(
    raw\_export\_dir = my\_drive / "Log\_Gemini/v1/0\_raw\_export",
    base\_dir       = my\_drive / "Log\_Gemini/v1",
)
print(result)
# {'n\_conversations': 3, 'n\_saved': 2, 'n\_skipped': 1, 'n\_zip\_batches': 1, ...}
```

増分更新は `incremental\_export` で、差分検出して NEW / UPDATED の会話だけを再生成します。

```python
result = gemini.incremental\_export(
    raw\_export\_dir = my\_drive / "Log\_Gemini/v1/0\_raw\_export",
    base\_dir       = my\_drive / "Log\_Gemini/v1",
)
print(result)
# {'n\_new': 1, 'n\_updated': 2, 'n\_unchanged': 50, ...}
```

ChatGPT 版・Claude 版もまったく同じインターフェースです。

```python
from pyreshape\_for\_notion import chatgpt, claude

chatgpt.full\_export(
    raw\_export\_dir = my\_drive / "Log\_ChatGPT/v3/0\_raw\_export",
    base\_dir       = my\_drive / "Log\_ChatGPT/v3",
)
claude.full\_export(
    raw\_export\_dir = my\_drive / "Log\_Claude/v2/0\_raw\_export",
    base\_dir       = my\_drive / "Log\_Claude/v2",
)
```

### ステップ 4: 低レベル API による細かい制御

各ステップを個別に呼ぶこともできます。

```python
from pyreshape\_for\_notion import gemini, core

# 1. パース (正規化会話のリストを得る)
convs = gemini.parse\_folder(my\_drive / "Log\_Gemini/v1/0\_raw\_export")

# 2. Notion MD 化
notion\_dir = my\_drive / "Log\_Gemini/v1/2\_notion\_md"
core.save\_notion\_md(convs, notion\_dir)

# 3. pcp 単位分割
split\_dir = my\_drive / "Log\_Gemini/v1/3\_notion\_md\_split"
core.split\_notion\_md\_files(notion\_dir, split\_dir, max\_pcps\_per\_part=25)

# 4. zip バッチ化
zip\_dir = my\_drive / "Log\_Gemini/v1/4\_zip\_batches"
core.make\_zip\_batches(split\_dir, zip\_dir, target=100, overflow=20)
```

正規化会話は 3 プラットフォームで共通のスキーマなので、`core` の関数はどのプラットフォームの `parse\_folder` 出力に対しても使えます。

## 出力フォルダ構成

`base\_dir` の直下に、処理の作成順に 0 始まりで連番を付したフォルダが生成されます。過度に nested にせず、すべて `base\_dir` 直下のフラット構成です。

```
base\_dir/
├── 0\_raw\_export/         入力。各サービスのエクスポートを置く
├── 1\_split\_json/         正規化済み JSON
├── 2\_notion\_md/          Notion 用 Markdown
├── 3\_notion\_md\_split/    pcp 単位分割した Markdown
├── 4\_zip\_batches/        初回 zip バッチ
├── 4\_zip\_batches\_diff/   差分 zip バッチ (増分更新時)
└── \_snapshot/            差分検出用スナップショット (管理用、番号なし)
```

フォルダ名は `pyreshape\_for\_notion.core.layout` に一元定義されています。変更したい場合はこのモジュールを編集してください。`DriveLayout` クラスで各パスを取得することもできます。

```python
from pyreshape\_for\_notion.core import DriveLayout
lay = DriveLayout(my\_drive / "Log\_Gemini/v1")
print(lay.notion\_md)   # .../Log\_Gemini/v1/2\_notion\_md
```

## 主要なパラメータ

`max\_pcps\_per\_part` (既定 25): 1 つの分割ファイルに含める pcp の最大数。

`target` / `overflow` (既定 100 / 20): 1 つの zip に含めるファイル数の目安と許容超過。Notion の Markdown インポートのレート制限 (12 時間あたり約 120 ファイル) を踏まえた値です。

`skip\_empty` (既定 True): 空会話 (本文がほぼ無い削除済みチャット等) を処理対象から除外するか。

`dedupe` (既定 True): 同一の prompt-completion ペアの重複を除去するか。Claude エクスポートのツリー分岐・再生成に由来する重複に対応します。

`shift\_body\_headings` (既定 False): 本文中の見出しレベルを 1 段繰り下げて pcp 見出しの下位に位置づけるか。既定では本文の見出しを原文のレベルのまま保持します。

## 出力される Markdown の構造

各会話は次の構造の Markdown に変換されます (v0.2.0)。

```markdown
# 会話タイトル

## pcp\_001

\*\*A Prompt by User\*\*

(プロンプト本文。インデントなし)

\*\*A Completion by LLM\*\*

(回答本文。見出し ## や箇条書きの階層、コードブロックがそのまま保持される)

---
```

v0.1.0 では pcp を箇条書き (`- pcp\_NNN`) で表現し本文を 4 スペース字下げしていましたが、これが Notion インポート時に本文中の見出しをプレーンテキスト化させ、箇条書き階層を壊す原因でした。v0.2.0 では pcp を見出し (`## pcp\_NNN`) で表現し本文を字下げしないことで、この問題を解消しています。

## テスト

```bash
pip install -e ".\[dev]"
pytest
```

`tests/test\_smoke.py` が 3 プラットフォームの end-to-end 動作を、`tests/test\_notion\_md\_v2.py` が見出し・階層の保持と重複除去を検証します。

## ライセンス

MIT License。個人利用を主目的としています。詳細は [LICENSE](LICENSE) を参照してください。

