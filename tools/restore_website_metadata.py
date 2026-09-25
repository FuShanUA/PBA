#!/usr/bin/env python3
"""Restore website card metadata from an older complete source snapshot."""

import argparse
import json
import subprocess
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEBSITE_PATH = ROOT / "data" / "sources" / "website.json"


class ChineseTitleParser(HTMLParser):
    """Extract a Chinese title from <title> or the first Chinese heading."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._capture = None
        self._chunks = []
        self.chinese_title = ""

    def handle_starttag(self, tag, attrs):
        if tag in ("title", "h1", "h2", "h3"):
            self._capture = tag
            self._chunks = []

    def handle_data(self, data):
        if self._capture is not None:
            self._chunks.append(data)

    def handle_endtag(self, tag):
        if self._capture != tag:
            return
        value = " ".join("".join(self._chunks).split())
        if value and self._contains_cjk(value) and not self.chinese_title:
            self.chinese_title = value
        self._capture = None
        self._chunks = []

    @staticmethod
    def _contains_cjk(value):
        return any("\u4e00" <= char <= "\u9fff" for char in value)


def load_revision(revision):
    raw = subprocess.check_output(
        ["git", "show", f"{revision}:data/sources/website.json"],
        cwd=ROOT,
    )
    return json.loads(raw.decode("utf-8"))


def chinese_page_title(slug):
    path = ROOT / "content" / "website" / slug / "page_zh.html"
    if not path.is_file():
        return ""
    parser = ChineseTitleParser()
    try:
        parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return ""
    return parser.chinese_title


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-rev", default="36154111")
    args = parser.parse_args()

    current = json.loads(WEBSITE_PATH.read_text(encoding="utf-8"))
    previous = load_revision(args.from_rev)
    previous_by_slug = {article["s"]: article for article in previous["articles"]}

    restored_fields = {"t": 0, "tt": 0, "th": 0, "ds": 0, "sn": 0}
    for article in current["articles"]:
        old = previous_by_slug.get(article["s"], {})
        for field in restored_fields:
            if old.get(field):
                article[field] = old[field]
                restored_fields[field] += 1

        old_title = old.get("tt", "")
        old_title_is_chinese = any("\u4e00" <= char <= "\u9fff" for char in old_title)
        page_title = chinese_page_title(article["s"])
        if page_title and not old_title_is_chinese:
            article["tt"] = page_title

        if not article.get("tt"):
            article["tt"] = article.get("t", "")

    WEBSITE_PATH.write_text(
        json.dumps(current, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    visible = [a for a in current["articles"] if not a.get("hidden") and not a.get("pending")]
    translated = [a for a in visible if any("\u4e00" <= c <= "\u9fff" for c in a.get("tt", ""))]
    thumbnails = [a for a in visible if a.get("th")]
    descriptions = [a for a in visible if a.get("ds")]
    print(f"articles: {len(current['articles'])}")
    print(f"visible: {len(visible)}")
    print(f"visible translated titles: {len(translated)}")
    print(f"visible thumbnails: {len(thumbnails)}")
    print(f"visible descriptions: {len(descriptions)}")
    print(f"fields restored from {args.from_rev}: {restored_fields}")


if __name__ == "__main__":
    main()
