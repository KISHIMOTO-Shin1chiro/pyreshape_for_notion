"""
pyreshape_for_notion.core.drive_io

ファイル入出力の抽象化レイヤ。

現状はローカルファイルシステム (Colab で drive.mount 済みの Drive を含む)
を対象とする。Cloud Run などへ移行する際は、ここに Drive API 実装を
追加することで上位層を変更せずに済む。

設計方針:
  - Colab では drive.mount('/content/drive') 済みの Drive を
    通常のファイルシステムとして扱える。そのため本モジュールは
    pathlib.Path をそのまま用いる薄いラッパとする。
  - mount_google_drive() は Colab 環境でのみ意味を持つ。
    ローカルテスト時は呼ばずに直接 Path を渡せる。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def mount_google_drive(mount_point: str = "/content/drive") -> Path:
    """
    Colab で Google Drive をマウントし、MyDrive の Path を返す。
    Colab 以外では ImportError となるため、その場合は直接 Path を扱うこと。
    """
    from google.colab import drive  # type: ignore
    mp = Path(mount_point)
    if not (mp / "MyDrive").exists():
        drive.mount(mount_point)
    return mp / "MyDrive"


def resolve_under_drive(my_drive: Path, path_in_drive: str) -> Path:
    """
    "/content/drive/MyDrive/Log_X/..." のような絶対パス表記、または
    "Log_X/..." のような相対表記の両方を受け付け、Path に解決する。
    """
    p = Path(path_in_drive)
    # 絶対パスで MyDrive を含む場合はそのまま
    if p.is_absolute():
        return p
    return my_drive / path_in_drive


def list_files(directory: Path, suffix: str = "",
               skip_underscore: bool = True) -> list[Path]:
    """ディレクトリ直下のファイルを列挙する (再帰しない)。"""
    if not directory.exists():
        raise FileNotFoundError(f"フォルダがありません: {directory}")
    out: list[Path] = []
    for p in directory.iterdir():
        if not p.is_file():
            continue
        if suffix and p.suffix != suffix:
            continue
        if skip_underscore and p.name.startswith("_"):
            continue
        out.append(p)
    return sorted(out)


def read_text(path: Path, encoding: str = "utf-8") -> str:
    return path.read_text(encoding=encoding)


def read_json(path: Path, encoding: str = "utf-8") -> Any:
    with open(path, "r", encoding=encoding) as f:
        return json.load(f)


def write_text(path: Path, text: str, encoding: str = "utf-8") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)
    return path


def write_json(path: Path, obj: Any, encoding: str = "utf-8",
               indent: int = 2) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding=encoding) as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
    return path


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
