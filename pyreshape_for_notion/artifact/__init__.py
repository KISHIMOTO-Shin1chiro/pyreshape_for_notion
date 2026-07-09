"""
pyreshape_for_notion.artifact

Claude の Artifacts として生成された「単体の Markdown 文書」を
Notion に取り込むためのサブパッケージ。

チャットエクスポート (chatgpt / claude / gemini パーサ) とは入力が異なる——
こちらは会話ではなく完成した文書一枚を扱う——ため、独立した名前空間に置く。

二つの経路:

  1. md → md (Notion の「Import → Text & Markdown」用)
     数式はコード化して中身を保存する。レンダリングはされないが、
     ``$true$`` 化のような内容の消失は起きない。

       from pyreshape_for_notion import artifact
       dst, stats = artifact.convert_file("CBM_syn_v0_1_3.md")

  2. md → Notion API ブロック (数式を実際にレンダリングしたい場合)
     ``$$...$$`` は equation ブロック、``$...$`` は equation リッチテキストへ。

       blocks = artifact.markdown_to_blocks(text, skip_first_h1=True)
       payload = artifact.make_page_payload(parent_id, artifact.extract_title(text), blocks)
       # requests.post("https://api.notion.com/v1/pages", json=payload, headers=...)
       for rest in artifact.chunk_blocks(blocks[100:]):
           ...  # PATCH /v1/blocks/{page_id}/children
"""

from __future__ import annotations

from .md_rewrite import (
    RewriteStats,
    rewrite_for_notion,
    convert_file,
    convert_folder,
)
from .uploader import (
    NotionClient,
    NotionAPIError,
    upload_markdown,
    upload_folder,
    normalize_page_id,
)
from .notion_blocks import (
    markdown_to_blocks,
    make_page_payload,
    chunk_blocks,
    extract_title,
    MAX_RICH_TEXT,
    MAX_CHILDREN,
)

__all__ = [
    "RewriteStats", "rewrite_for_notion", "convert_file", "convert_folder",
    "markdown_to_blocks", "make_page_payload", "chunk_blocks", "extract_title",
    "MAX_RICH_TEXT", "MAX_CHILDREN",
    "NotionClient", "NotionAPIError",
    "upload_markdown", "upload_folder", "normalize_page_id",
]
