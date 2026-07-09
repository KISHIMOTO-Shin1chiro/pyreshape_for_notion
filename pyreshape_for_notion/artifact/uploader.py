"""
pyreshape_for_notion.artifact.uploader

Markdown を Notion API 経由でアップロードし、数式を equation ブロック /
equation リッチテキストとして**実際にレンダリングされる形**でページ化する。

なぜ md インポートではだめか (pcp_005):
  Notion の「Import → Text & Markdown」は ``$...$`` / ``$$...$$`` を数式として
  解釈しない。md 経路で可能なのは「中身を壊されずに運ぶ」ことまでであり、
  インポート時点でのレンダリングは API でブロックを直接構成する以外にない。

依存: 標準ライブラリのみ (urllib)。requests も SDK も不要。

使い方 (Colab / ローカル共通):

    from pyreshape_for_notion.artifact import upload_markdown

    url = upload_markdown(
        "CBM_axiomatic_system_syntactic_subsystem_v0_1_3.md",
        parent_page_id="https://www.notion.so/xxxx-24c3...",  # ページ URL のままで可
        token="ntn_...",                                       # integration secret
    )
    print(url)

前提 (一度だけの設定):
  1. https://www.notion.so/my-integrations で Internal Integration を作成し
     token (secret) を得る。
  2. アップロード先の親ページを開き、右上 ...  → 「接続 (Connections)」→
     作成した integration を追加する。これを忘れると 404 が返る。

API 制約への対処:
  - children は 1 リクエスト 100 ブロックまで → 自動分割
  - レート制限 (平均 3 req/s) → リクエスト間に既定 0.34 s の待機
  - 429 / 5xx → Retry-After を尊重して指数バックオフで再試行
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from .notion_blocks import (
    markdown_to_blocks,
    extract_title,
    chunk_blocks,
    MAX_CHILDREN,
)

__all__ = [
    "NotionClient",
    "NotionAPIError",
    "upload_markdown",
    "upload_folder",
    "normalize_page_id",
]

API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# transport は試験時に差し替えられる:  (method, url, payload, headers) -> (status, dict)
Transport = Callable[[str, str, dict | None, dict], tuple[int, dict]]


class NotionAPIError(RuntimeError):
    """Notion API がエラーを返したときに送出される。"""

    def __init__(self, status: int, body: dict):
        self.status = status
        self.body = body
        code = body.get("code", "unknown")
        msg = body.get("message", "")
        hint = ""
        if status == 401:
            hint = "\n  hint: token が誤っています (ntn_ / secret_ で始まる integration secret を渡してください)。"
        elif status == 404:
            hint = ("\n  hint: 親ページが integration に共有されていません。"
                    "ページ右上の … → 接続 (Connections) から integration を追加してください。")
        super().__init__(f"Notion API {status} [{code}] {msg}{hint}")


# ============================================================
# page id の正規化
# ============================================================
_HEX32_RE = re.compile(r"[0-9a-fA-F]{32}")
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def normalize_page_id(page: str) -> str:
    """
    ページ URL・ハイフンなし 32 桁・UUID のいずれからも、
    ハイフン付き UUID を取り出す。

      "https://www.notion.so/My-Page-24c384a9c2f9807fb35bd6d17ede073c"
      "24c384a9c2f9807fb35bd6d17ede073c"
      "24c384a9-c2f9-807f-b35b-d6d17ede073c"
        -> "24c384a9-c2f9-807f-b35b-d6d17ede073c"
    """
    page = page.strip()
    m = _UUID_RE.search(page)
    if m:
        return m.group(0).lower()
    # URL 中に 32 桁 hex が複数ある場合 (?v= のビュー id 等) は最後を採る
    ms = _HEX32_RE.findall(page.split("?")[0])
    if not ms:
        raise ValueError(
            f"ページ id を抽出できません: {page!r}\n"
            "  Notion のページ URL、または 32 桁の id を渡してください。")
    h = ms[-1].lower()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# ============================================================
# HTTP クライアント
# ============================================================
def _default_transport(method: str, url: str, payload: dict | None,
                       headers: dict) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return res.status, json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {"message": str(e)}
        # Retry-After ヘッダを body に載せて上位へ
        ra = e.headers.get("Retry-After") if e.headers else None
        if ra:
            body["_retry_after"] = ra
        return e.code, body


class NotionClient:
    """
    最小の Notion API クライアント。

      client = NotionClient(token)
      page_id, url = client.create_page(parent_id, title, blocks)
    """

    def __init__(
        self,
        token: str,
        notion_version: str = NOTION_VERSION,
        min_interval: float = 0.34,        # 平均 3 req/s 制限への備え
        max_retries: int = 5,
        transport: Transport | None = None,
    ):
        if not token or not token.strip():
            raise ValueError("token が空です。Notion integration secret を渡してください。")
        self._headers = {
            "Authorization": f"Bearer {token.strip()}",
            "Notion-Version": notion_version,
            "Content-Type": "application/json",
        }
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._transport = transport or _default_transport
        self._last_call = 0.0

    # ---------- 低レベル ----------
    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        url = API_BASE + path
        for attempt in range(self._max_retries + 1):
            # レート制限: 前回呼び出しからの間隔を確保
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            status, body = self._transport(method, url, payload, self._headers)
            self._last_call = time.monotonic()

            if status < 400:
                return body
            if status in (429, 502, 503) and attempt < self._max_retries:
                ra = body.get("_retry_after")
                delay = float(ra) if ra else min(2.0 ** attempt, 30.0)
                time.sleep(delay)
                continue
            raise NotionAPIError(status, body)
        raise NotionAPIError(599, {"message": "retries exhausted"})  # 到達しない

    # ---------- 高レベル ----------
    def create_page(self, parent_page_id: str, title: str,
                    blocks: list[dict]) -> tuple[str, str]:
        """
        ページを作成し、100 ブロックを超える分は追記で流し込む。
        返り値: (page_id, page_url)
        """
        parent_id = normalize_page_id(parent_page_id)
        payload = {
            "parent": {"type": "page_id", "page_id": parent_id},
            "properties": {"title": {
                "title": [{"type": "text", "text": {"content": title[:2000]}}]}},
            "children": blocks[:MAX_CHILDREN],
        }
        res = self._request("POST", "/pages", payload)
        page_id = res["id"]
        page_url = res.get("url", f"https://www.notion.so/{page_id.replace('-', '')}")

        for chunk in chunk_blocks(blocks[MAX_CHILDREN:]):
            self._request("PATCH", f"/blocks/{page_id}/children",
                          {"children": chunk})
        return page_id, page_url


# ============================================================
# 公開関数
# ============================================================
def upload_markdown(
    src: str | Path,
    parent_page_id: str,
    token: str,
    title: str | None = None,
    skip_first_h1: bool = True,
    paragraph_join: str = "smart",
    client: NotionClient | None = None,
    verbose: bool = True,
) -> str:
    """
    md ファイル (またはフォルダ内の 1 ファイル) を Notion ページとして
    アップロードする。数式は equation ブロック / リッチテキストとして
    レンダリングされる。返り値は作成されたページの URL。

      src            : md ファイルのパス、または md テキストそのもの
      parent_page_id : 親ページの URL / id (URL をそのまま貼ってよい)
      token          : Notion integration secret
      title          : 省略時は md の先頭 H1 (なければファイル名)
    """
    p = Path(src) if not str(src).lstrip().startswith(("#", "$", "|", ">")) else None
    if p is not None and p.exists():
        text = p.read_text(encoding="utf-8-sig")
        fallback = p.stem
    else:
        text = str(src)
        fallback = "Untitled"

    page_title = title or extract_title(text, fallback=fallback)
    blocks = markdown_to_blocks(
        text, paragraph_join=paragraph_join, skip_first_h1=skip_first_h1)

    cli = client or NotionClient(token)
    page_id, url = cli.create_page(parent_page_id, page_title, blocks)
    if verbose:
        eq_blocks = sum(1 for b in blocks if b["type"] == "equation")
        print(f"  {page_title}: {len(blocks)} blocks "
              f"(equation ブロック {eq_blocks} 件) -> {url}")
    return url


def upload_folder(
    src_dir: str | Path,
    parent_page_id: str,
    token: str,
    pattern: str = "*.md",
    exclude_suffix: str = "_notion",
    **kwargs,
) -> list[tuple[Path, str]]:
    """
    フォルダ内の md をそれぞれ 1 ページとしてアップロードする。
    ``*_notion.md`` (md インポート用の退避版) は既定で除外する——
    API 経路では原本をそのまま送るのが正であるため。
    返り値: [(md パス, ページ URL), ...]
    """
    src_dir = Path(src_dir)
    files = [q for q in sorted(src_dir.glob(pattern))
             if not (exclude_suffix and q.stem.endswith(exclude_suffix))]
    if not files:
        raise FileNotFoundError(f"変換対象の md がありません: {src_dir}")

    client = NotionClient(token)
    out: list[tuple[Path, str]] = []
    for q in files:
        url = upload_markdown(q, parent_page_id, token,
                              client=client, **kwargs)
        out.append((q, url))
    return out
