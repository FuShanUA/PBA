#!/usr/bin/env python3
"""Audit visible website pages for missing or partial Chinese translations."""

import argparse
import json
import sys
from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scrapers.translate_parallel import BOILERPLATE_SELECTORS, remove_form_sections, should_skip_text


CONTENT_DIR = ROOT / "content" / "website"
WEBSITE_PATH = ROOT / "data" / "sources" / "website.json"
NONTRANSLATABLE_TAGS = ("svg", "pre", "code", "script", "style", "textarea")
MIN_TEXT_CHARS = 100
LOW_CHINESE_RATIO = 0.20
MIN_UNTRANSLATED_NODES = 3
MIN_NODE_WORDS = 8
MIN_PROSE_CHARS = 300
STRUCTURAL_TAGS = ("img", "video", "iframe", "source", "table")
URL_ATTRIBUTES = ("src", "href", "poster", "data-src", "srcset", "data-srcset")


def article(path):
    soup = BeautifulSoup(path.read_text(errors="ignore"), "html.parser")
    body = soup.find("body")
    if body is None:
        return None
    for node in body.select(BOILERPLATE_SELECTORS):
        node.decompose()
    remove_form_sections(body)
    return body


def prose_text(node):
    return " ".join(
        str(string)
        for string in node.find_all(string=True)
        if not string.find_parent(NONTRANSLATABLE_TAGS)
    )


def contains_cjk(value):
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def is_bilingual_original(text, translated_text):
    """Recognize English originals retained in parentheses beside Chinese."""
    start = 0
    while True:
        position = translated_text.find(text, start)
        if position < 0:
            return False
        prefix = translated_text[max(0, position - 40):position]
        suffix_start = position + len(text)
        suffix = translated_text[suffix_start:suffix_start + 40]
        if contains_cjk(prefix) or contains_cjk(suffix):
            return True
        start = suffix_start


def local_asset_count(path):
    soup = BeautifulSoup(path.read_text(errors="ignore"), "html.parser")
    count = 0
    for tag in soup.find_all(True):
        for attribute in URL_ATTRIBUTES:
            value = tag.get(attribute)
            if isinstance(value, str) and (
                value.startswith("/assets/") or value.startswith("//")
            ):
                count += 1
    return count


def structural_counts(node):
    return {tag: len(node.find_all(tag)) for tag in STRUCTURAL_TAGS}


def audit_page(en_path, zh_path):
    slug = en_path.parent.name
    if not zh_path.exists() or zh_path.stat().st_size <= 200:
        return {"slug": slug, "reason": "missing", "chinese_ratio": 0.0}

    en_article = article(en_path)
    zh_article = article(zh_path)
    if en_article is None or zh_article is None:
        return {"slug": slug, "reason": "missing_article_element", "chinese_ratio": 0.0}

    zh_text = prose_text(zh_article)
    chinese_chars = sum("\u4e00" <= char <= "\u9fff" for char in zh_text)
    ascii_letters = sum(char.isalpha() and char.isascii() for char in zh_text)
    denominator = chinese_chars + ascii_letters
    ratio = chinese_chars / denominator if denominator else 0.0

    untranslated_nodes = []
    for node in en_article.find_all(string=True):
        if node.find_parent(NONTRANSLATABLE_TAGS):
            continue
        text = " ".join(str(node).split())
        if should_skip_text(text):
            continue
        if (
            len(text.split()) >= MIN_NODE_WORDS
            and text in zh_text
            and not is_bilingual_original(text, zh_text)
        ):
            untranslated_nodes.append(text)

    en_structure = structural_counts(en_article)
    zh_structure = structural_counts(zh_article)
    structural_differences = {
        tag: {"en": en_count, "zh": zh_structure[tag]}
        for tag, en_count in en_structure.items()
        if en_count != zh_structure[tag]
    }
    local_assets = local_asset_count(zh_path)

    reasons = []
    if len(untranslated_nodes) >= MIN_UNTRANSLATED_NODES:
        reasons.append("untranslated_source_nodes")
    if denominator >= MIN_PROSE_CHARS and ratio < LOW_CHINESE_RATIO:
        reasons.append("low_chinese_ratio")
    if structural_differences:
        reasons.append("structural_mismatch")
    if local_assets:
        reasons.append("local_or_protocol_relative_assets")
    if not reasons:
        return None

    return {
        "slug": slug,
        "reason": ",".join(reasons),
        "chinese_ratio": round(ratio, 4),
        "text_chars": denominator,
        "untranslated_nodes": len(untranslated_nodes),
        "structural_differences": structural_differences,
        "local_assets": local_assets,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="-")
    args = parser.parse_args()

    website = json.loads(WEBSITE_PATH.read_text(encoding="utf-8"))
    visible_slugs = {
        article["s"]
        for article in website.get("articles", [])
        if not article.get("hidden") and not article.get("pending")
    }
    untranslated_titles = sorted(
        article["s"]
        for article in website.get("articles", [])
        if article["s"] in visible_slugs
        and not contains_cjk(article.get("tt", ""))
    )

    findings = []
    for en_path in sorted(CONTENT_DIR.glob("*/page.html")):
        if en_path.parent.name not in visible_slugs:
            continue
        finding = audit_page(en_path, en_path.with_name("page_zh.html"))
        if finding:
            findings.append(finding)

    payload = {
        "visible_pages": len(visible_slugs),
        "untranslated_card_titles": len(untranslated_titles),
        "untranslated_card_title_slugs": untranslated_titles,
        "findings_count": len(findings),
        "findings": findings,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output == "-":
        print(rendered)
    else:
        output = ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
        print(
            f"Visible pages: {len(visible_slugs)}; findings: {len(findings)}; "
            f"wrote {output}"
        )


if __name__ == "__main__":
    main()
