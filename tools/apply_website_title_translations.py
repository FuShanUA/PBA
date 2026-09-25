#!/usr/bin/env python3
"""Apply the maintained Chinese title map to website cards and pages."""

import json
from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
WEBSITE_PATH = ROOT / "data" / "sources" / "website.json"
TITLE_MAP_PATH = ROOT / "data" / "website_title_zh.json"


def contains_cjk(value):
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def update_page_title(slug, title):
    path = ROOT / "content" / "website" / slug / "page_zh.html"
    if not path.is_file():
        return False

    original = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(original, "html.parser")
    changed = False

    if soup.title and soup.title.get_text(strip=True) != title:
        soup.title.string = title
        changed = True

    heading = soup.find("h1")
    if heading and not contains_cjk(heading.get_text(" ", strip=True)):
        heading.clear()
        heading.append(title)
        changed = True

    if not changed:
        return False

    path.write_text(str(soup), encoding="utf-8")
    return True


def main():
    website = json.loads(WEBSITE_PATH.read_text(encoding="utf-8"))
    title_map = json.loads(TITLE_MAP_PATH.read_text(encoding="utf-8"))
    slugs = {article.get("s") for article in website.get("articles", [])}

    unknown = sorted(set(title_map) - slugs)
    if unknown:
        raise SystemExit("Title map contains unknown slugs: " + ", ".join(unknown))

    updated_cards = 0
    updated_pages = 0
    for article in website.get("articles", []):
        title = title_map.get(article.get("s"))
        if not title:
            continue
        if article.get("tt") != title:
            article["tt"] = title
            updated_cards += 1
        if update_page_title(article["s"], title):
            updated_pages += 1

    WEBSITE_PATH.write_text(
        json.dumps(website, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    visible = [
        article
        for article in website.get("articles", [])
        if not article.get("hidden") and not article.get("pending")
    ]
    translated = [
        article
        for article in visible
        if contains_cjk(article.get("tt", ""))
    ]
    unmapped = sorted(
        article["s"]
        for article in visible
        if not contains_cjk(article.get("tt", ""))
    )
    print(f"Card titles updated: {updated_cards}")
    print(f"Page titles updated: {updated_pages}")
    print(f"Visible translated titles: {len(translated)}/{len(visible)}")
    if unmapped:
        print("Unmapped visible titles: " + ", ".join(unmapped))


if __name__ == "__main__":
    main()
