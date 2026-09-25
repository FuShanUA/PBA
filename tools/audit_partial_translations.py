#!/usr/bin/env python3
"""Find historical Chinese pages that contain untranslated English fallbacks."""

import argparse
import json
import sys
from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scrapers.translate_parallel import should_skip_text

CONTENT_DIR = ROOT / "content" / "docs"
NONTRANSLATABLE_TAGS = ("svg", "pre", "code", "script", "style", "textarea")
MIN_TEXT_CHARS = 100
LOW_CHINESE_RATIO = 0.20
MIN_UNTRANSLATED_NODES = 2
MIN_NODE_WORDS = 8
MIN_PROSE_CHARS = 300


def article(path):
    soup = BeautifulSoup(path.read_text(errors="ignore"), "html.parser")
    return soup.find("article")


def visible_text(node):
    return " ".join(node.stripped_strings)


def visible_prose_text(node):
    return " ".join(
        str(string)
        for string in node.find_all(string=True)
        if not string.find_parent(NONTRANSLATABLE_TAGS)
    )


def audit_page(en_path, zh_path):
    en_path = Path(en_path)
    zh_path = Path(zh_path)
    if not zh_path.exists() or zh_path.stat().st_size <= 200:
        return {"slug": en_path.parent.name, "reason": "missing", "chinese_ratio": 0.0}

    en_article = article(en_path)
    zh_article = article(zh_path)
    if en_article is None or zh_article is None:
        return None

    zh_text = visible_prose_text(zh_article)
    chinese_chars = sum("\u4e00" <= char <= "\u9fff" for char in zh_text)
    ascii_letters = sum(char.isalpha() and char.isascii() for char in zh_text)
    denominator = chinese_chars + ascii_letters
    if denominator < MIN_TEXT_CHARS:
        return None

    ratio = chinese_chars / denominator
    untranslated_nodes = []
    for node in en_article.find_all(string=True):
        if node.find_parent(NONTRANSLATABLE_TAGS):
            continue
        text = " ".join(str(node).split())
        if should_skip_text(text):
            continue
        if len(text.split()) >= MIN_NODE_WORDS and text in zh_text:
            untranslated_nodes.append(text)

    reasons = []
    if len(untranslated_nodes) >= MIN_UNTRANSLATED_NODES:
        reasons.append("untranslated_source_nodes")
    if (
        ratio < LOW_CHINESE_RATIO
        and denominator >= MIN_PROSE_CHARS
        and len(untranslated_nodes) >= MIN_UNTRANSLATED_NODES
    ):
        reasons.append("low_chinese_ratio")
    if not reasons:
        return None

    return {
        "slug": en_path.parent.name,
        "reason": ",".join(reasons),
        "chinese_ratio": round(ratio, 4),
        "untranslated_nodes": len(untranslated_nodes),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="-")
    args = parser.parse_args()

    findings = []
    for en_path in sorted(CONTENT_DIR.glob("*/page.html")):
        finding = audit_page(en_path, en_path.with_name("page_zh.html"))
        if finding:
            findings.append(finding)

    payload = {"count": len(findings), "findings": findings}
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output == "-":
        print(rendered)
    else:
        output = ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Found {len(findings)} pages; wrote {output}")


if __name__ == "__main__":
    main()
