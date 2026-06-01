"""
pyreshape_for_notion.chatgpt.parser

ChatGPT 公式エクスポート (conversations-*.json, 各ファイルに会話の配列)
をパースし、正規化済み会話 (NormalizedConv) を生成する。

ChatGPT は mapping (ノードの木構造) を持つため、これを線形メッセージ列に
変換する正規化が必要。旧 Code_001 (chatgpt) のロジックを移植。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.schema import NormalizedConv, make_conversation, make_message


def _ts_to_iso(ts: Any) -> str:
    if not isinstance(ts, (int, float)):
        return ""
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        return ""


def _extract_text_from_parts(parts: list[Any]) -> tuple[str, list[str]]:
    text_parts: list[str] = []
    image_refs: list[str] = []
    for p in parts or []:
        if isinstance(p, str):
            if p:
                text_parts.append(p)
        elif isinstance(p, dict):
            ct = p.get("content_type")
            if ct == "image_asset_pointer":
                ap = p.get("asset_pointer", "") or ""
                if ap:
                    image_refs.append(ap)
                    text_parts.append(f"[image: {ap}]")
            else:
                t = p.get("text") or ""
                if t:
                    text_parts.append(t)
    return "\n".join(text_parts), image_refs


def _classify_message(msg: dict[str, Any]) -> dict[str, Any] | None:
    author = msg.get("author") or {}
    role = author.get("role") or ""
    name = author.get("name") or ""
    content = msg.get("content") or {}
    ctype = content.get("content_type")
    metadata = msg.get("metadata") or {}

    if role == "system":
        if not metadata.get("is_user_system_message"):
            return None
        if ctype == "text":
            text, _ = _extract_text_from_parts(content.get("parts") or [])
        else:
            return None
        if not text.strip():
            return None
        return {"role": "system", "render_kind": "system_instruction",
                "text": text, "extra": {"author_name": name}}

    if role not in ("user", "assistant", "tool"):
        return None

    extra: dict[str, Any] = {}
    if name:
        extra["author_name"] = name
    text = ""
    render_kind = "text"

    if ctype == "text":
        text, image_refs = _extract_text_from_parts(content.get("parts") or [])
        if image_refs:
            extra["image_refs"] = image_refs
    elif ctype == "multimodal_text":
        text, image_refs = _extract_text_from_parts(content.get("parts") or [])
        if image_refs:
            render_kind = "image_ref"
            extra["image_refs"] = image_refs
    elif ctype == "code":
        text = content.get("text") or ""
        render_kind = "code"
        lang = content.get("language")
        if lang:
            extra["language"] = lang
    elif ctype == "execution_output":
        text = content.get("text") or ""
        render_kind = "exec_output"
    elif ctype == "tether_quote":
        text = content.get("text") or ""
        render_kind = "search_result"
        domain = content.get("domain")
        if domain:
            extra["source_domain"] = domain
    elif ctype == "tether_browsing_display":
        text = content.get("result") or ""
        render_kind = "search_result"
    elif ctype == "system_error":
        text = content.get("text") or content.get("name") or ""
        render_kind = "system_error"
    else:
        return None

    if not text.strip():
        return None
    return {"role": role, "render_kind": render_kind,
            "text": text, "extra": extra}


def _process_citation_markers(
    text: str,
    content_references: list[dict[str, Any]] | None,
) -> str:
    """
    ChatGPT の引用マーカー (PUA 文字 \\ue200...\\ue201 で囲まれた cite トークン)
    を本文から除去し、metadata.content_references にある全 URL を本文末尾に
    「## このターンの参考文献」セクションとして列挙する。

    背景 (pcp_022_007 〜 pcp_022_010):
      ChatGPT のエクスポートには、UI レンダリング時にハイパーリンクへ変換される
      予定の特殊マーカー (turn{X}{view|search|news}{N} を PUA 文字で囲んだもの)
      が含まれており、pyreshape の出力では文字化けの原因になっていた。

      マーカー id (turn{X}view0 等) と metadata.content_references の
      (turn_index, ref_type, ref_index) の紐付けロジックは ChatGPT 内部仕様で
      公開されておらず、また安定的に解明することも困難であった (pcp_022_009 で
      順序対応・セット一致など複数の仮説を実証データで検証したが、いずれも
      正確な対応が得られなかった)。

      そこで pcp_022_010 では、紐付けは諦めるが情報は失わない X-1 方針を採用:
        - 本文中のマーカーは番号付きリンクに置換せず、純粋に除去 (可読性確保)
        - 当該メッセージの metadata.content_references にある全 URL を
          本文末尾に「## このターンの参考文献」として列挙 (情報の保全)

    引数:
      text             : 本文 (assistant メッセージ)
      content_references: msg.metadata.content_references

    返り値:
      クリーニング済み本文 (引用マーカー除去 + 参考文献セクション付加)
    """
    import re as _re

    # 本文中のマーカーを除去 (PUA 文字を含む cite トークン全体)
    # マーカー種別: 通常の web 引用 (\ue200cite\ue202turn{X}{type}{N}\ue201)
    #              ファイル引用     (\ue200filecite\ue202turn{X}file{Y}\ue201)
    # 「\ue200 で始まり \ue201 で終わる任意トークン」を一括除去するのが安全。
    MARKER_RE = _re.compile(r'\ue200[^\ue200\ue201]*\ue201')
    cleaned = MARKER_RE.sub("", text or "")
    # 残った PUA 文字 (E200-E202) の念のための除去
    cleaned = _re.sub(r'[\ue200-\ue202]', '', cleaned)

    # content_references の全 URL を重複排除しながら列挙
    if not content_references:
        return cleaned

    seen_urls: set[str] = set()
    refs_in_order: list[dict[str, str]] = []
    for r in content_references:
        items = r.get("items") or []
        for it in items:
            url = it.get("url") or ""
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            refs_in_order.append({
                "url": url,
                "title": it.get("title") or "",
                "attribution": it.get("attribution") or "",
            })

    if not refs_in_order:
        return cleaned

    # 末尾に参考文献セクションを付加
    lines = ["", "", "## このターンの参考文献", ""]
    for i, r in enumerate(refs_in_order, 1):
        title = (r["title"] or "").strip()
        attr = (r["attribution"] or "").strip()
        url = r["url"]
        # title が URL 文字列そのもの (ChatGPT 側でタイトル取得失敗時) は
        # 表示として使わない
        title_is_url = title.startswith("http://") or title.startswith("https://")
        if title and not title_is_url:
            display = title
            attr_part = f" ({attr})" if attr and attr != title else ""
        elif attr:
            display = attr
            attr_part = ""
        else:
            # URL からホスト名を抽出
            host = url
            for prefix in ("https://", "http://"):
                if host.startswith(prefix):
                    host = host[len(prefix):]
                    break
            host = host.split("/")[0]
            display = host or "(no title)"
            attr_part = ""
        lines.append(f"{i}. [{display}]({url}){attr_part}")
    section = "\n".join(lines)

    return cleaned.rstrip() + section


def _merge_consecutive_assistant_texts(
    nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    ChatGPT (特に GPT-5 系) で 1 回答が複数 assistant(text) に分割される
    現象に対処する。「human から次の human までの間に出現するすべての
    assistant(text)」を 1 つの assistant メッセージに連結する。

    入力: _create_time でソート済みのノードリスト (ChatGPT パーサ内部形式)
    出力: マージ後のノードリスト

    マージ規則:
      - 各 human から次の human までの区間 (1 つの「ターン」) を識別
      - その区間内のすべての (sender=="assistant" かつ render_kind=="text")
        ノードを 1 つに連結する
      - 連結したテキストは "\n\n" で結合 (本来の段落区切りを保つ)
      - マージ後のノードは「最初に出現した assistant(text) の位置」に置き、
        uuid・created_at は最初のノードのものを引き継ぐ
      - assistant(code) / tool / system / その他は変更せず保持する
        (後段の pair_into_pcps が無視するので結果に影響しない)

    Claude/Gemini への影響: なし (この関数は ChatGPT パーサからのみ呼ばれる)。
    """
    if not nodes:
        return nodes

    # 各 human の位置を特定し、human と次の human の間で区間を区切る
    # 最後の human の後は「リスト末尾まで」を区間とする
    human_positions = [i for i, n in enumerate(nodes) if n["sender"] == "human"]

    # 各区間で連結対象 (assistant かつ render_kind=='text') を見つける
    # 削除対象の index と、保持される最初の assistant(text) の index, 連結内容を記録
    indices_to_delete: set[int] = set()
    merges: dict[int, str] = {}  # keep_idx -> merged_text

    # 区間: [human_pos+1, 次のhuman_pos) または [human_pos+1, len(nodes))
    boundaries = human_positions + [len(nodes)]
    for k in range(len(human_positions)):
        start = human_positions[k] + 1
        end = boundaries[k + 1]
        # この区間にある assistant(text) を集める
        at_indices = [
            i for i in range(start, end)
            if nodes[i]["sender"] == "assistant"
            and nodes[i].get("render_kind") == "text"
            and (nodes[i].get("text") or "").strip()
        ]
        if len(at_indices) <= 1:
            continue  # 連結不要 (0 or 1 個)

        # 最初の位置に連結内容を残し、他は削除対象
        keep_idx = at_indices[0]
        merged = "\n\n".join(nodes[i]["text"] for i in at_indices)
        merges[keep_idx] = merged
        for i in at_indices[1:]:
            indices_to_delete.add(i)

    # 結果リストを構築
    result: list[dict[str, Any]] = []
    for i, n in enumerate(nodes):
        if i in indices_to_delete:
            continue
        if i in merges:
            new_node = dict(n)  # 浅いコピー (extra は dict だが書き換えない)
            new_node["text"] = merges[i]
            result.append(new_node)
        else:
            result.append(n)
    return result


def normalize_conv(raw: dict[str, Any]) -> NormalizedConv:
    """ChatGPT の生会話 dict (mapping 構造) を正規化会話に変換する。"""
    mapping = raw.get("mapping") or {}
    nodes: list[dict[str, Any]] = []

    for node_id, node in mapping.items():
        if not isinstance(node, dict):
            continue
        msg = node.get("message")
        if not isinstance(msg, dict):
            continue
        classified = _classify_message(msg)
        if classified is None:
            continue

        role = classified["role"]
        if role == "user":
            sender = "human"
        elif role == "assistant":
            sender = "assistant"
        elif role == "tool":
            sender = "tool"
        else:
            sender = "system"

        # pcp_022_010 (ChatGPT 固有, 0.5.4): assistant の text メッセージで
        # PUA 文字を含む引用マーカーを除去し、metadata.content_references の
        # 全 URL を本文末尾に「## このターンの参考文献」として列挙する。
        # 本文中マーカーと URL の正確な紐付けは ChatGPT 内部仕様非公開のため
        # 諦め (pcp_022_009 参照), マーカー除去 + 全 URL 保持の方針を採用。
        text = classified["text"]
        if (sender == "assistant"
                and classified["render_kind"] == "text"
                and "\ue200" in text):
            content_refs = (msg.get("metadata") or {}).get("content_references")
            text = _process_citation_markers(text, content_refs)

        ts = msg.get("create_time")
        nodes.append({
            "uuid": msg.get("id") or node_id,
            "sender": sender,
            "raw_role": role,
            "render_kind": classified["render_kind"],
            "text": text,
            "extra": classified["extra"],
            "created_at": _ts_to_iso(ts),
            "updated_at": _ts_to_iso(msg.get("update_time") or ts),
            "_create_time": ts if isinstance(ts, (int, float)) else 0.0,
        })

    nodes.sort(key=lambda n: n["_create_time"])

    # pcp_022_005 修正 (ChatGPT 固有, 0.5.2):
    # GPT-5 系モデル (gpt-5-5-pro 等) は 1 つの回答を複数の assistant(text)
    # メッセージに分割して送出することがある:
    #   human → assistant(text: 前置き) → assistant(code: search)
    #         → tool(結果) → assistant(text: 整理) → assistant(text: 本論)
    #         → human(次の質問)
    # 現行の pair_into_pcps は最初の assistant(text) のみを採用するため、
    # 本論が捨てられる症状があった。ここで「human から次の human までの間に
    # 出現するすべての assistant(text)」を 1 つの assistant メッセージに
    # マージしてから後段に渡す。
    # 注意: この処理は ChatGPT パーサ内で完結し、Claude/Gemini には影響しない。
    nodes = _merge_consecutive_assistant_texts(nodes)

    conv_id = raw.get("id") or raw.get("conversation_id") or ""
    name = raw.get("title") or ""
    created_at = _ts_to_iso(raw.get("create_time"))
    updated_at = _ts_to_iso(raw.get("update_time"))

    messages = []
    for i, n in enumerate(nodes):
        messages.append(make_message(
            uuid=n["uuid"],
            sender=n["sender"],
            text=n["text"],
            index=i,
            raw_role=n["raw_role"],
            render_kind=n["render_kind"],
            created_at=n["created_at"],
            updated_at=n["updated_at"],
            extra=n["extra"],
        ))

    return make_conversation(
        uuid=conv_id,
        name=name,
        messages=messages,
        created_at=created_at,
        updated_at=updated_at,
        source={"platform": "chatgpt"},
    )


def load_export(path: Path) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if isinstance(data, dict):
        # 単一会話の場合
        return [data]
    if not isinstance(data, list):
        raise ValueError(
            f"想定外のトップレベル型: {type(data).__name__}.")
    return data


def parse_file(export_path: Path) -> list[NormalizedConv]:
    raw_list = load_export(Path(export_path))
    return [normalize_conv(r) for r in raw_list]


def parse_folder(input_dir: Path) -> list[NormalizedConv]:
    """
    フォルダ内のすべての conversations-*.json を読み、会話を結合して返す。
    """
    input_dir = Path(input_dir)
    if not input_dir.exists():
        raise FileNotFoundError(f"フォルダがありません: {input_dir}")
    convs: list[NormalizedConv] = []
    for p in sorted(input_dir.iterdir()):
        if p.suffix == ".json" and not p.name.startswith("_"):
            convs.extend(parse_file(p))
    return convs
