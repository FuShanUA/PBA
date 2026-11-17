#!/usr/bin/env python3
"""Sync source-index Chinese titles into translated local pages."""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCES_DIR = ROOT / "data" / "sources"


def translated_path(source, article):
    slug = article.get("s")
    if not slug:
        return None
    if source in ("website", "docs"):
        return ROOT / "content" / source / slug / "page_zh.html"
    return ROOT / "articles" / slug / "reader_zh.html"


def update_page(path, title, update_heading=False):
    if not path.is_file():
        return False

    html = path.read_text(encoding="utf-8")
    updated = html
    changed = False

    def replace_title(match):
        nonlocal changed
        current = re.sub(r"\s+", " ", match.group(1)).strip()
        normalized_title = re.sub(r"\s+", " ", title).strip()
        if current == normalized_title:
            return match.group(0)
        changed = True
        return f"<title>{title}</title>"

    updated = re.sub(r"<title[^>]*>(.*?)</title>", replace_title, updated, count=1, flags=re.I | re.S)
    if "<title" not in updated.lower():
        head_match = re.search(r"<head\b[^>]*>", updated, re.I)
        if head_match:
            insert_at = head_match.end()
            updated = updated[:insert_at] + f"<title>{title}</title>" + updated[insert_at:]
            changed = True

    h1_match = re.search(r"<h1\b[^>]*>(.*?)</h1>", updated, re.I | re.S)
    if update_heading and h1_match:
        current = re.sub(r"<[^>]+>", "", h1_match.group(1))
        current = re.sub(r"\s+", " ", current).strip()
        if current != re.sub(r"\s+", " ", title).strip():
            updated = updated[:h1_match.start()] + f"<h1>{title}</h1>" + updated[h1_match.end():]
            changed = True

    if changed:
        path.write_text(updated, encoding="utf-8")
    return changed


def main():
    updated = 0
    checked = 0
    for source_path in sorted(SOURCES_DIR.glob("*.json")):
        source = source_path.stem
        data = json.loads(source_path.read_text(encoding="utf-8"))
        for article in data.get("articles", []):
            title = article.get("tt") or article.get("t")
            if not title or title == article.get("t"):
                continue
            path = translated_path(source, article)
            if path is None or not path.is_file():
                continue
            checked += 1
            if update_page(path, title, update_heading=source == "blog"):
                updated += 1

    print(f"Translated pages checked: {checked}")
    print(f"Titles synced: {updated}")


if __name__ == "__main__":
    main()
