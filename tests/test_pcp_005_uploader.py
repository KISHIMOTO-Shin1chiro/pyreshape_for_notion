"""
tests/test_pcp_005_uploader.py

pcp_005: Notion API アップローダの回帰テスト。
実 API は叩かず、transport 差し替えでリクエスト列を検証する。
"""

from __future__ import annotations

import pytest

from pyreshape_for_notion.artifact import uploader
from pyreshape_for_notion.artifact.uploader import (
    NotionClient,
    NotionAPIError,
    normalize_page_id,
    upload_markdown,
)


# ============================================================
# 1. page id の正規化
# ============================================================
UUID = "24c384a9-c2f9-807f-b35b-d6d17ede073c"
HEX = UUID.replace("-", "")


@pytest.mark.parametrize("raw", [
    UUID,
    HEX,
    f"https://www.notion.so/My-Page-{HEX}",
    f"https://www.notion.so/ws/My-Page-{HEX}?pvs=4",
    f"  {UUID}  ",
])
def test_normalize_page_id(raw):
    assert normalize_page_id(raw) == UUID


def test_normalize_page_id_picks_last_hex_before_query():
    # ?v= 以降のビュー id は無視される
    url = f"https://www.notion.so/{HEX}?v=ffffffffffffffffffffffffffffffff"
    assert normalize_page_id(url) == UUID


def test_normalize_page_id_rejects_garbage():
    with pytest.raises(ValueError):
        normalize_page_id("https://www.notion.so/My-Page")


# ============================================================
# 2. モック transport
# ============================================================
class FakeTransport:
    """リクエストを記録し、台本どおりに応答する。"""

    def __init__(self, script=None):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.script = list(script or [])

    def __call__(self, method, url, payload, headers):
        self.calls.append((method, url, payload))
        if self.script:
            return self.script.pop(0)
        if method == "POST" and url.endswith("/pages"):
            return 200, {"id": UUID, "url": f"https://www.notion.so/{HEX}"}
        return 200, {"results": []}


def make_client(transport):
    return NotionClient("ntn_dummy", transport=transport, min_interval=0.0)


# ============================================================
# 3. create_page の分割送信
# ============================================================
def test_create_page_single_request_under_100():
    tr = FakeTransport()
    cli = make_client(tr)
    blocks = [{"object": "block", "type": "divider", "divider": {}}] * 99
    cli.create_page(UUID, "T", blocks)
    assert len(tr.calls) == 1
    method, url, payload = tr.calls[0]
    assert (method, payload["parent"]["page_id"]) == ("POST", UUID)
    assert len(payload["children"]) == 99


def test_create_page_chunks_over_100():
    tr = FakeTransport()
    cli = make_client(tr)
    blocks = [{"object": "block", "type": "divider", "divider": {}}] * 250
    cli.create_page(UUID, "T", blocks)
    # POST 1 回 + PATCH 2 回 (100/100/50)
    assert [c[0] for c in tr.calls] == ["POST", "PATCH", "PATCH"]
    assert len(tr.calls[0][2]["children"]) == 100
    assert len(tr.calls[1][2]["children"]) == 100
    assert len(tr.calls[2][2]["children"]) == 50
    assert tr.calls[1][1].endswith(f"/blocks/{UUID}/children")


def test_create_page_accepts_url_as_parent():
    tr = FakeTransport()
    cli = make_client(tr)
    cli.create_page(f"https://www.notion.so/My-Page-{HEX}", "T",
                    [{"object": "block", "type": "divider", "divider": {}}])
    assert tr.calls[0][2]["parent"]["page_id"] == UUID


# ============================================================
# 4. リトライとエラー
# ============================================================
def test_retry_on_429_then_success():
    tr = FakeTransport(script=[
        (429, {"code": "rate_limited", "message": "slow down", "_retry_after": "0"}),
        (200, {"id": UUID, "url": "u"}),
    ])
    cli = make_client(tr)
    cli.create_page(UUID, "T", [])
    assert len(tr.calls) == 2


def test_error_401_has_token_hint():
    tr = FakeTransport(script=[(401, {"code": "unauthorized", "message": "bad"})])
    cli = make_client(tr)
    with pytest.raises(NotionAPIError) as ei:
        cli.create_page(UUID, "T", [])
    assert "token" in str(ei.value)


def test_error_404_has_connection_hint():
    tr = FakeTransport(script=[(404, {"code": "object_not_found", "message": "x"})])
    cli = make_client(tr)
    with pytest.raises(NotionAPIError) as ei:
        cli.create_page(UUID, "T", [])
    assert "共有" in str(ei.value)


def test_empty_token_rejected():
    with pytest.raises(ValueError):
        NotionClient("  ")


# ============================================================
# 5. upload_markdown (エンドツーエンド、モック)
# ============================================================
MD = """# CBM テスト文書

**形式文.** 質量関数 $m : \\Theta \\to [0,1]$、$\\sum_{v} m(v) = 1$。

$$
\\varepsilon(\\mathtt{00}) = (1,1)
$$
"""


def test_upload_markdown_from_file(tmp_path):
    src = tmp_path / "doc.md"
    src.write_text(MD, encoding="utf-8")
    tr = FakeTransport()
    cli = make_client(tr)
    url = upload_markdown(src, UUID, "ntn_dummy", client=cli, verbose=False)
    assert url == f"https://www.notion.so/{HEX}"

    payload = tr.calls[0][2]
    # タイトルは先頭 H1、本文からは除外される
    assert payload["properties"]["title"]["title"][0]["text"]["content"] == "CBM テスト文書"
    types = [b["type"] for b in payload["children"]]
    assert "heading_1" not in types
    assert "equation" in types                       # $$ ブロック
    para = next(b for b in payload["children"] if b["type"] == "paragraph")
    assert any(rt["type"] == "equation" for rt in para["paragraph"]["rich_text"])


def test_upload_markdown_from_text_uses_h1():
    tr = FakeTransport()
    cli = make_client(tr)
    upload_markdown(MD, UUID, "ntn_dummy", client=cli, verbose=False)
    assert tr.calls[0][2]["properties"]["title"]["title"][0]["text"]["content"] \
        == "CBM テスト文書"


def test_upload_folder_excludes_notion_suffix(tmp_path):
    (tmp_path / "a.md").write_text("# A\n\n$x$\n", encoding="utf-8")
    (tmp_path / "a_notion.md").write_text("# A\n\n`$x$`\n", encoding="utf-8")
    tr = FakeTransport()
    # NotionClient を内部生成させず、モノをモックに差し替えるため monkeypatch 的に:
    from pyreshape_for_notion.artifact import uploader as U

    orig = U.NotionClient
    U.NotionClient = lambda token, **kw: make_client(tr)   # type: ignore
    try:
        results = U.upload_folder(tmp_path, UUID, "ntn_dummy", verbose=False)
    finally:
        U.NotionClient = orig                              # type: ignore
    assert [p.name for p, _ in results] == ["a.md"]


def test_coded_math_md_is_restored_by_upload(tmp_path):
    """経路 1 の出力 (*_notion.md 相当) を API 経路に流しても数式へ復元される。"""
    src = tmp_path / "doc.md"
    src.write_text("係数 `$\\alpha$` は\n\n```latex\nE = mc^{2}\n```\n", encoding="utf-8")
    tr = FakeTransport()
    cli = make_client(tr)
    upload_markdown(src, UUID, "ntn_dummy", client=cli, verbose=False)
    children = tr.calls[0][2]["children"]
    eq_block = [b for b in children if b["type"] == "equation"]
    assert eq_block and eq_block[0]["equation"]["expression"] == "E = mc^{2}"
    para = next(b for b in children if b["type"] == "paragraph")
    assert any(rt["type"] == "equation" and rt["equation"]["expression"] == "\\alpha"
               for rt in para["paragraph"]["rich_text"])
