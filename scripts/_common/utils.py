"""Common utilities used by scripts under scripts/reports and wrappers.

Provides repository root detection and default export/pages directories.
Keep this file minimal — more helpers can be added here later.
"""
from pathlib import Path
import os
import json
from typing import Any

# Repo root (two levels up from scripts/_common/utils.py -> repo root)
ROOT = Path(__file__).resolve().parents[2]

# Default export directory under repo root
EXPORT_DIR = ROOT / 'wiki_down_upload_export'
PAGES_DIR = EXPORT_DIR / 'pages'

def detect_export_dir() -> Path:
    """Return the export directory to use.

    Priority:
    - environment variable EXPORT_DIR if set
    - default EXPORT_DIR under repo root
    - current working directory / wiki_down_upload_export
    """
    env = os.environ.get('EXPORT_DIR')
    if env:
        p = Path(env)
        if p.exists():
            return p
    if EXPORT_DIR.exists():
        return EXPORT_DIR
    fallback = Path.cwd() / 'wiki_down_upload_export'
    return fallback

def detect_import_dir() -> Path:
    """Return the import directory to use.

    Priority:
    - environment variable IMPORT_DIR if set
    - default 'wiki_down_upload_import' under repo root
    - current working directory / wiki_down_upload_import
    """
    env = os.environ.get('IMPORT_DIR')
    if env:
        p = Path(env)
        if p.exists():
            return p
    default = ROOT / 'wiki_down_upload_import'
    if default.exists():
        return default
    return Path.cwd() / 'wiki_down_upload_import'

def read_json(path: Path) -> Any:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def write_text(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(data)

__all__ = [
    'ROOT', 'EXPORT_DIR', 'PAGES_DIR', 'detect_export_dir', 'read_json', 'write_text'
]

