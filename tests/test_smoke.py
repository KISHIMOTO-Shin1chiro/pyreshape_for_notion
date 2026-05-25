"""pyreshape_for_notion のスモークテスト (全プラットフォーム end-to-end)。"""
import shutil
import json
from pathlib import Path

from pyreshape_for_notion import gemini, claude, chatgpt


def _make_gemini_md(prompt, comp, exported="2026/5/13 15:00:00"):
    return (f"# Gemini Chat Export\n\n> Exported on: {exported}\n\n---\n\n"
            f"## 👤 You\n\n{prompt}\n\n## 🤖 Gemini\n\n{comp}\n\n---\n")


def test_gemini_full_export(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "2025-12-19_A.md").write_text(
        _make_gemini_md("pcp_001 質問", "回答"), encoding="utf-8")
    (raw / "2025-12-20_B.md").write_text(
        _make_gemini_md("pcp_002 質問B", "回答B"), encoding="utf-8")

    result = gemini.full_export(raw_export_dir=raw, base_dir=tmp_path / "out")
    assert result["n_conversations"] == 2
    assert result["n_saved"] == 2
    assert result["n_zip_batches"] == 1


def test_gemini_incremental(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "2025-12-19_A.md").write_text(
        _make_gemini_md("pcp_001 質問", "回答"), encoding="utf-8")

    base = tmp_path / "out"
    gemini.incremental_export(raw_export_dir=raw, base_dir=base)
    r2 = gemini.incremental_export(raw_export_dir=raw, base_dir=base)
    assert r2["n_unchanged"] == 1
    assert r2["n_new"] == 0


def test_claude_parser(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    export = [{
        "uuid": "c1", "name": "T",
        "created_at": "2025-12-19T10:00:00+00:00",
        "updated_at": "2025-12-19T15:00:00+00:00",
        "chat_messages": [
            {"uuid": "m1", "sender": "human", "index": 0, "text": "q"},
            {"uuid": "m2", "sender": "assistant", "index": 1, "text": "a"},
        ],
    }]
    (raw / "conversations.json").write_text(
        json.dumps(export, ensure_ascii=False), encoding="utf-8")
    convs = claude.parse_folder(raw)
    assert len(convs) == 1
    assert convs[0]["uuid"] == "c1"
    assert len(convs[0]["chat_messages"]) == 2


def test_chatgpt_parser(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    export = [{
        "id": "g1", "title": "T",
        "create_time": 1734588000.0, "update_time": 1734606000.0,
        "mapping": {
            "root": {"id": "root", "parent": None, "children": ["n1"], "message": None},
            "n1": {"id": "n1", "parent": "root", "children": ["n2"],
                   "message": {"id": "n1", "author": {"role": "user"},
                               "create_time": 1734588000.0,
                               "content": {"content_type": "text", "parts": ["q"]},
                               "metadata": {}}},
            "n2": {"id": "n2", "parent": "n1", "children": [],
                   "message": {"id": "n2", "author": {"role": "assistant"},
                               "create_time": 1734588060.0,
                               "content": {"content_type": "text", "parts": ["a"]},
                               "metadata": {}}},
        },
    }]
    (raw / "conversations.json").write_text(
        json.dumps(export, ensure_ascii=False), encoding="utf-8")
    convs = chatgpt.parse_folder(raw)
    assert len(convs) == 1
    assert convs[0]["chat_messages"][0]["sender"] == "human"
