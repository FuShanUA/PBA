#!/usr/bin/env python3
"""Convert website media and site links to absolute palantir.com URLs."""

from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "website"
BASE_URL = "https://www.palantir.com"
URL_ATTRIBUTES = ("src", "href", "poster", "data-src")
SRCSET_ATTRIBUTES = ("srcset", "data-srcset")


def normalize_url(value):
    value = value.strip()
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("/assets/"):
        return BASE_URL + value
    if value.startswith("/") and not value.startswith("//"):
        return BASE_URL + value
    return value


def normalize_srcset(value):
    candidates = []
    changed = False
    for candidate in value.split(","):
        parts = candidate.strip().split()
        if not parts:
            continue
        normalized = normalize_url(parts[0])
        changed = changed or normalized != parts[0]
        candidates.append(" ".join([normalized, *parts[1:]]))
    return ", ".join(candidates), changed


def fix_file(path):
    original = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(original, "html.parser")
    changed = False

    for tag in soup.find_all(True):
        for attribute in URL_ATTRIBUTES:
            value = tag.get(attribute)
            if not isinstance(value, str):
                continue
            normalized = normalize_url(value)
            if normalized != value:
                tag[attribute] = normalized
                changed = True
        for attribute in SRCSET_ATTRIBUTES:
            value = tag.get(attribute)
            if not isinstance(value, str):
                continue
            normalized, attribute_changed = normalize_srcset(value)
            if attribute_changed:
                tag[attribute] = normalized
                changed = True

    if changed:
        path.write_text(str(soup), encoding="utf-8")
    return changed


def main():
    changed_files = 0
    checked_files = 0
    for path in sorted(CONTENT_DIR.glob("*/page*.html")):
        checked_files += 1
        if fix_file(path):
            changed_files += 1
    print(f"Checked {checked_files} website HTML files")
    print(f"Rewrote {changed_files} files with absolute URLs")


if __name__ == "__main__":
    main()
