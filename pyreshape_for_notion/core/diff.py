"""
pyreshape_for_notion.core.diff

正規化済み会話の差分検出 (Code_004 中核ロジック) を 3 プラットフォーム
共通実装として集約。

差分のカテゴリ:
  - NEW           : snapshot に無い会話
  - UPDATED       : snapshot にあるが fingerprint が変化
  - UNCHANGED     : fingerprint 一致
  - DELETED       : snapshot にあるが現在の入力に無い
  - SKIPPED_EMPTY : 空会話 (本文がほぼ無い)

fingerprint:
  (updated_at, content_hash)
  content_hash = chat_messages を index 順に正規化した JSON の SHA-1
  → メッセージの追加・編集の両方を検出できる。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .schema import NormalizedConv, is_empty_chat


# ============================================================
# fingerprint
# ============================================================
def conv_fingerprint(conv: NormalizedConv) -> tuple[str, str]:
    """
    (updated_at, content_hash) を返す。
    content_hash は chat_messages の正規化 JSON の SHA-1。
    メッセージ追加・既存メッセージ編集の双方で hash が変化する。
    """
    updated_at = conv.get("updated_at") or ""
    msgs = conv.get("chat_messages", [])
    msgs_sorted = sorted(msgs, key=lambda m: m.get("index", 0))
    minimal = [
        {
            "uuid": m.get("uuid"),
            "sender": m.get("sender"),
            "index": m.get("index"),
            "text": m.get("text"),
        }
        for m in msgs_sorted
    ]
    payload = json.dumps(minimal, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return updated_at, digest


# ============================================================
# 差分計算
# ============================================================
def compute_diff(
    new_convs: list[NormalizedConv],
    old_index: dict[str, dict[str, Any]],
    skip_empty: bool = True,
    empty_threshold: float = 0.95,
) -> dict[str, list[tuple[int, NormalizedConv]]]:
    """
    new_convs : 今回読み込んだ会話のリスト
    old_index : snapshot の {uuid: {fingerprint, name, updated_at, ...}}
    """
    result: dict[str, list[tuple[int, NormalizedConv]]] = {
        "new": [], "updated": [], "unchanged": [],
        "deleted": [], "skipped_empty": [],
    }

    seen_ids: set[str] = set()
    for i, c in enumerate(new_convs):
        cid = c.get("uuid")
        if not cid:
            result["updated"].append((i, c))
            continue
        seen_ids.add(cid)

        if skip_empty:
            is_empty, stats = is_empty_chat(c, threshold=empty_threshold)
            if is_empty:
                rec = {**c, "_empty_stats": stats}
                result["skipped_empty"].append((i, rec))
                continue

        old_rec = old_index.get(cid)
        if old_rec is None:
            result["new"].append((i, c))
            continue
        new_fp = conv_fingerprint(c)
        old_fp = tuple(old_rec.get("fingerprint") or ("", ""))
        if new_fp == old_fp:
            result["unchanged"].append((i, c))
        else:
            result["updated"].append((i, c))

    for cid, old_rec in old_index.items():
        if cid not in seen_ids:
            pseudo = {
                "uuid": cid,
                "name": old_rec.get("name", ""),
                "updated_at": old_rec.get("updated_at", ""),
                "_source": old_rec.get("_source", {}),
            }
            result["deleted"].append((-1, pseudo))
    return result


# ============================================================
# snapshot 構築 / 読込
# ============================================================
def build_snapshot(
    convs: list[NormalizedConv],
    skip_empty: bool = True,
    empty_threshold: float = 0.95,
    saved_at: str = "",
) -> dict[str, Any]:
    records: dict[str, Any] = {}
    for c in convs:
        cid = c.get("uuid")
        if not cid:
            continue
        if skip_empty:
            is_empty, _ = is_empty_chat(c, threshold=empty_threshold)
            if is_empty:
                continue
        fp = conv_fingerprint(c)
        records[cid] = {
            "name": c.get("name", ""),
            "updated_at": c.get("updated_at", ""),
            "fingerprint": list(fp),
            "_source": c.get("_source", {}),
        }
    return {"saved_at": saved_at, "records": records}


def load_snapshot_records(snapshot_obj: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return snapshot_obj.get("records") or {}
