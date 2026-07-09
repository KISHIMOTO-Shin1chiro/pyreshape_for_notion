# 変更履歴

このプロジェクトの主要な変更点を記録します。バージョン番号は [セマンティック バージョニング](https://semver.org/lang/ja/) に従います。

## [0.7.0] - 2026-07-09

### 追加 (pcp_005)

- `artifact.upload_markdown` / `artifact.upload_folder` / `artifact.NotionClient` を追加しました。md を Notion API 経由でページ化し、数式を **equation ブロック / equation リッチテキストとしてインポート時点からレンダリングされる形**で取り込みます。
- 背景: Notion の「Import → Text & Markdown」は `$...$` / `$$...$$` を数式として解釈しません。0.6.0 の md → md 経路 (数式のコード退避) は内容を保全しますが、レンダリングは原理的に不可能です。レンダリングまで求める場合は md インポータを迂回して API でブロックを構成する必要があり、0.6.0 では変換器 (`markdown_to_blocks`) まで提供していました。0.7.0 はその上にアップロード層を載せ、ワンストップにしたものです。

### 実装

- 依存は標準ライブラリのみ (urllib)。`requests` も公式 SDK も不要で、Colab で追加インストールなしに動きます。
- `parent_page_id` には Notion のページ URL をそのまま貼れます (`normalize_page_id` が URL / 32 桁 hex / UUID を吸収)。
- children 100 ブロック制限に合わせた自動分割、平均 3 req/s のレート制限に合わせた送信間隔 (既定 0.34 s)、429/5xx への指数バックオフ再試行 (Retry-After 尊重) を実装しています。
- 401 (token 不正) と 404 (integration 未共有) には、原因と対処を日本語で添えた例外を送出します。
- `upload_folder` は `*_notion.md` (md インポート用の退避版) を既定で除外します。API 経路では原本を送るのが正であるためです。ただし退避版を誤って送っても、`markdown_to_blocks` の `restore_coded_math` により数式へ復元されます (テストで担保)。

### テスト

- `tests/test_pcp_005_uploader.py` (18 件) を追加しました。transport 差し替えによるモックで、分割送信・リトライ・id 正規化・エラーヒント・経路 1 出力の復元アップロードを検証します。実 API との疎通はネットワーク制約上未検証のため、API 契約は Notion 公式ドキュメント (2022-06-28 版) に依拠しています。

### 使用前の準備 (一度だけ)

1. https://www.notion.so/my-integrations で Internal Integration を作成し、secret (token) を取得します。
2. アップロード先の親ページで … → 接続 (Connections) → 作成した integration を追加します。これを忘れると 404 になります。

## [0.6.0] - 2026-07-09

### 追加

- サブパッケージ `pyreshape_for_notion.artifact` を新設しました。チャットエクスポートではなく、**Claude の Artifacts として生成された単体の Markdown 文書**を Notion に取り込むための層です (pcp_000 で報告)。
- `core.mathsafe` を新設しました。Markdown を「素のテキスト / コードフェンス / インラインコード / インライン数式 / ブロック数式」のセグメント列に分解する共通スキャナです。`"".join(seg.raw) == 原文` を不変条件として保証し、下流の変換器が正規表現を本文に直接当てないようにします。

### 修正 (pcp_000)

- 数式を含む md を Notion の「Import → Text & Markdown」に投入すると、数式スパンが本文中に `$true$` という文字列として現れ、LaTeX の中身が失われる問題に対処しました。デリミタが残り中身だけが `true` に置換されるという挙動は、KaTeX のレンダリング失敗ではなく、インポータのインライン規則が照合結果の真偽値をそのまま本文に書き出していることを示唆します。いずれにせよ md 経路では数式の中身が救えないため、二つの迂回路を用意しました。

  1. **`artifact.rewrite_for_notion` (md → md)**: インライン数式を インラインコード `` `$...$` `` へ、ブロック数式を ```` ```latex ```` フェンスへ退避します。コード領域はインポータが一切解釈しないため、LaTeX ソースが完全に保存されます。レンダリングはされませんが、内容の消失は起きません。
  2. **`artifact.markdown_to_blocks` (md → Notion API ブロック)**: md インポータを迂回し、`$$...$$` を `equation` ブロック、`$...$` を `equation` リッチテキストとして構成します。Notion 上で KaTeX により実際にレンダリングされます。数式が本体である文書 (公理論的サブシステム等) はこちらを使ってください。

### 実装上の注意

- 保護領域の判定を `core.mathsafe` に一元化しました。コードフェンス内の `$`、インラインコード内の `\mathsf T`、エスケープされた `\$` を数式と誤認しません。
- `$4 \times 4$` のように `$` の直後が数字で始まる数式が実在するため、通貨ヒューリスティクスは採用しません。
- 行をまたぐインライン数式 (原文の折り返しで生じる) を検出し、コード化の際に単一行へ畳みます。
- `_` による強調は解釈しません。`pcp_002_008` のような識別子をイタリック化する事故を避けるためです。
- 強調・リンクの走査は保護領域をマスクした写像上で行います。`**$^{\intercal}$ へ改記**` のように強調が数式をまたぐ場合に閉じ記号を見失わないためです。
- 表の行に含まれるコードスパン内の `|` を `\|` にエスケープします。
- H4 以降を太字段落へ降格します (Notion の見出しは H3 まで)。
- 和文のハードラップ行を、ブロック化の際に空白を挟まず連結します (`paragraph_join="smart"`)。

### 影響範囲

- 既存の `chatgpt` / `claude` / `gemini` パーサ、`core.notion_cleanup`、`core.notion_md` の挙動は変更していません。新機能はすべて `artifact` 名前空間に閉じています。
- 回帰テスト `tests/test_pcp_000_artifact_md.py` (45 件) を追加しました。既存テスト 89 件はそのまま通過します。

## [0.5.5] - 2026-06-02

### 修正

- ChatGPT 由来エクスポートで、本文中の TeX 式 (`\(...\)`、`\[...\]`) が Notion 上で文字化けたり、記号が削除された不完全な表示になる問題を修正しました (pcp_022_011 で報告)。
- Notion の Markdown インポートは LaTeX 標準デリミタ (`\(...\)`、`\[...\]`) を数式として認識しないため、これらをそのまま渡すと `\Omega`、`\mathrm{...}`、`\bigwedge` などの命令が「不明なエスケープ」として削除される現象が発生していました。0.5.5 では、ChatGPT パーサ内で LaTeX 標準デリミタを Notion (KaTeX) 互換の `$...$`、`$$...$$` に変換します。
- ChatGPT が同じ数式を二重出力する形式 (`\[...\]` 本体 + `` ```tex `` フェンス) について、後者の `` ```tex `` および `` ```latex `` フェンスを除去するようにしました (前者が `$$...$$` として正しく数式表示されるため、後者は冗長で本文を圧迫していた)。

### 変更 (互換性のあるデフォルト変更)

- `core.notion_cleanup.clean_for_notion` の引数 `convert_block_math` の既定値を `True` から `False` に変更しました。
- 0.4.0 で導入した当時、`$$...$$` を Notion がブロック数式として認識できなかったため inline code (`` ` ``) に変換していました。しかし現在の Notion は `$$...$$` をブロック数式として正しく認識するため、変換すると逆に数式表示を壊してしまいます。新しい既定では `$$...$$` を保持します。旧挙動が必要な場合は `convert_block_math=True` を明示してください。

### 影響範囲

- ChatGPT エクスポート: 本文中の TeX 式が Notion 上で正しくレンダリングされるようになります。`\[...\]` ブロック数式は KaTeX レンダリング、`\(...\)` インライン数式は変数記号として表示されます。
- Claude / Gemini: TeX デリミタ変換は ChatGPT パーサ内に局所化しているため、影響なし。両プラットフォームで `\(...\)` や `\[...\]` を含むメッセージはそのまま保持されます (両者が標準で出力する場合は別途同様の処置が必要)。
- `notion_cleanup` の既定変更は全プラットフォーム共通ですが、これも `$$...$$` を正しく数式として残す方向の変更であり、表示が改善するか不変かのいずれかです。

### 追加

- 回帰テスト `tests/test_pcp_022_012_tex_normalize.py` (14 件) を追加しました。Claude / Gemini が影響を受けないことを明示的にテストする項目も含みます。
- 既存テスト (`tests/test_notion_cleanup.py`) を新しい既定値に合わせて更新しました。

### 既存ユーザの対応

- 0.5.4 以前で生成済みの ChatGPT フォルダで TeX 式を含む会話は、Notion 上で式が崩れて表示されています。0.5.5 にアップグレード後、ChatGPT 側で `full_export` をもう一度実行すれば、正しく数式レンダリングされる md に再生成されます。Claude / Gemini のフォルダは再生成不要です。

## [0.5.4] - 2026-06-01

### 修正

- ChatGPT エクスポートで、本文中の引用と引用文献リストが文字化けて残る問題を修正しました (pcp_022_007 で報告)。
- 原因は、ChatGPT が web 検索ツールやファイル添付の引用を本文中に Unicode Private Use Area 文字 (U+E200, U+E201, U+E202) で囲まれた特殊マーカー (`cite turn{X}view{N}`, `filecite turn{X}file{Y}` 等) として埋め込んでおり、これが UI レンダリング時にハイパーリンクへ変換される設計だったためです。pyreshape はこれらを除去できておらず、Notion に取り込んだ際に「citeturn430856search0」のような不可読な文字列として残っていました。
- 0.5.4 では、本文中の引用マーカーをすべて除去し、`metadata.content_references` にある全 URL を「## このターンの参考文献」として各 assistant メッセージの末尾に番号付きリンクで列挙します。

### 設計判断 (pcp_022_009 〜 pcp_022_010)

- 当初、本文中マーカーの id (`turn792083view0` 等) と `content_references` の `{turn_index, ref_type, ref_index}` を紐付けて、本文中に番号付き脚注 `[^N]` を埋め込む方針 (B-3) を検討しましたが、ChatGPT 内部仕様は非公開で、実データの検証 (順序対応、セット一致など複数の仮説) でも安定的な紐付けロジックを得られませんでした。
- そこで、紐付けは諦め、マーカーを除去 + 全 URL を末尾に列挙する方針 (X-1) を採用しました。本文中の引用番号と参考文献の正確な対応はありませんが、「この回答で参照されたソース」の完全な情報は保持されます。実装の信頼性と保守性を優先した判断です。

### 影響範囲

- ChatGPT (引用を含む会話): 大幅に改善。文字化け解消、URL 情報も完全保持。
- ChatGPT (引用なしの会話): 影響なし。
- Claude / Gemini: **完全に影響なし**。修正は `pyreshape_for_notion/chatgpt/parser.py` 内のみ。

### 追加

- 回帰テスト `tests/test_pcp_022_010_chatgpt_citations.py` (14 件) を追加しました。Claude / Gemini が影響を受けないことを明示的にテストする項目も含みます。
- 参考文献リストの表示テキスト fallback ロジックを追加しました。優先順位は `title > attribution > URL のホスト名` で、`title` フィールドに URL 文字列がそのまま入っているケース (ChatGPT 側でタイトル取得失敗時) では URL ではなく attribution (サイト名) を表示テキストとして使います。Notion 上で読みやすい表示になります。

### 既存ユーザの対応

- 0.5.3 以前で `2_notion_md` / `3_notion_md_renamed` の ChatGPT フォルダを生成済みの場合、web 検索を含む会話は引用マーカーが文字化けた状態で保存されています。0.5.4 にアップグレード後、ChatGPT 側で `full_export` をもう一度実行すれば、クリーンな本文と参考文献セクション付きで再生成されます。Claude / Gemini のフォルダは再生成不要です。

## [0.5.3] - 2026-05-30

### 修正

- Gemini エクスポートで、回答本文中の `---` (水平線) を会話区切りと誤認し、長い Gemini 回答の本論が捨てられていた問題を修正しました (pcp_022_006 で報告)。
- Gemini は長い回答内で `---` を `### 検証セクション` や `### 結論` のような節の前の構造区切りとして使うことがあります。0.5.2 までの Gemini パーサは `---` を見つけた時点で無条件にメッセージを確定していたため、回答が「導入」「本論」「結論」のように分割され、本論以降が捨てられたり、重複した「導入だけのメッセージ」として現れたりしていました。
- 0.5.3 では、`---` の次に出現する非空行が `## 👤 You` または `## 🤖 Gemini` の場合のみ会話区切りとして扱い、それ以外は本文の一部 (構造区切り) として保持するようにしました。

### 影響範囲

- Gemini エクスポート: 大幅に改善。実テスト (Completed_2026-01-09 Part 1) では、復元される assistant 総文字数が約 107,000 文字から約 376,000 文字 (3.5 倍) に増加し、本論が完全に含まれるようになりました。
- ChatGPT / Claude: **完全に影響なし**。修正は `pyreshape_for_notion/gemini/parser.py` 内のみで、他は一切変更していません。

### 追加

- 回帰テスト `tests/test_pcp_022_006_gemini_inline_hr.py` (6 件) を追加しました。ChatGPT / Claude が影響を受けないことを明示的にテストする項目も含みます。

### 既存ユーザの対応

- 0.5.2 以前で `2_notion_md` / `3_notion_md_renamed` の Gemini フォルダを生成済みの場合、長い Gemini 回答は不完全な内容で保存されています。0.5.3 にアップグレード後、Gemini 側で `full_export` をもう一度実行すれば、全文が含まれた状態に再生成されます。ChatGPT / Claude のフォルダは再生成不要です。

## [0.5.2] - 2026-05-30

### 修正

- ChatGPT GPT-5 系モデル (gpt-5-5-pro 等) のエクスポートで、各 completion の冒頭の前置きだけが取り込まれ、本論が捨てられていた問題を修正しました (pcp_022_005 で報告)。
- GPT-5 系は 1 つの回答を複数の `assistant(text)` メッセージに分割して送出するため、0.5.1 までの「最初の assistant(text) で pair 完了」というロジックでは前置き部分しか保存されませんでした。0.5.2 では、ChatGPT パーサ内で「human から次の human までの間に出現するすべての `assistant(text)`」を `\n\n` で連結した上で、後段の `pair_into_pcps` に渡します。これにより、前置き・整理・本論を含む完全な回答が Notion MD に出力されます。

### 影響範囲

- ChatGPT (GPT-5 系を含む): 大幅に改善。1 回答が複数 text に分割されるケースで、全文が連結されて出力される。
- ChatGPT (GPT-4 系など、1 回答 = 1 text のケース): 影響なし (連結対象が 1 個以下のため何も変更されない)。
- Claude / Gemini: **完全に影響なし**。修正は `pyreshape_for_notion/chatgpt/parser.py` 内のみで、core も他プラットフォームのパーサも一切変更していません。

### 追加

- 回帰テスト `tests/test_pcp_022_005_multi_text_merge.py` (8 件) を追加しました。Claude / Gemini が影響を受けないことを明示的にテストする項目も含みます。

### 既存ユーザの対応

- 0.5.1 以前で `2_notion_md` / `3_notion_md_renamed` を生成済みの場合、ChatGPT の GPT-5 系を使った会話は不完全な内容 (前置きだけ) で保存されています。0.5.2 にアップグレード後、ChatGPT 側で `full_export` をもう一度実行すれば、全文が含まれた状態に再生成されます。Claude / Gemini のフォルダは再生成不要です。

## [0.5.1] - 2026-05-30

### 修正

- ChatGPT のツール使用 (旧 Code Interpreter / 検索など) を含む会話で、本来の最終回答が捨てられ、`search("...")` のようなツール呼び出しコードが回答として記録される問題を修正しました (pcp_022 で報告)。
- 症状として「拡張推論が入ると以降のチャットが切れる」ように見えていましたが、原因は `pair_into_pcps` が「human の次に出現した assistant メッセージ」を無条件で pair の相手にしていたことでした。
- 修正後は `render_kind == "text"` の assistant メッセージのみを pair の相手とし、間に挟まる `assistant(code)` (search/mclick 呼び出し) や `tool` (検索結果) はスキップします。本来の最終回答が正しく Notion MD に出力されるようになります。

### 影響範囲

- ChatGPT のツール使用を含む会話: 大幅に改善 (失われていた最終回答が復活)
- Claude / Gemini の通常会話: 影響なし (両者の assistant は `render_kind="text"` のみ)

### 追加

- 回帰テスト `tests/test_pcp_022_tool_use_pairing.py` (7 件) を追加しました。

### 既存ユーザの対応

- 0.5.0 以前で `2_notion_md` / `3_notion_md_renamed` を生成済みの場合、ツール使用を含む ChatGPT の会話は誤った内容で保存されています。0.5.1 にアップグレード後、ChatGPT 側の `full_export` をもう一度実行することで、正しい内容に再生成されます。Claude / Gemini のフォルダは再生成不要です。

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
