#!/usr/bin/env python3
"""Backfill website publication dates and secondary-navigation translations."""

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

try:
    from PIL import Image, ImageStat
except ImportError:
    Image = None
    ImageStat = None


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scrapers"))

from website_tags import TAG_ZH
from website_dates import build_date_counts, extract_page_publish_date, normalize_date
from website_taxonomy import categorize_article, is_non_content_path


WEBSITE_PATH = os.path.join(ROOT, "data", "sources", "website.json")
CACHE_PATH = os.path.join(ROOT, "data", "website_publish_dates.json")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
NON_ENGLISH_URL_RE = re.compile(r"/(?:de|fr|es|ja|zh|ko|pt|it)(?:/|$)")


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def local_date(article):
    path = Path(ROOT) / article.get("hp", "")
    if not path.is_file():
        return "", ""
    try:
        html = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "", ""
    return extract_page_publish_date(html)


def remote_date(article, timeout, retries):
    command = [
        "curl",
        "-L",
        "--silent",
        "--show-error",
        "--fail",
        "--compressed",
        "--max-time",
        str(timeout),
        "--retry",
        str(retries),
        "--retry-all-errors",
        "-A",
        USER_AGENT,
        article["u"],
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout * (retries + 1) + 15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "", ""
    if result.returncode != 0 or not result.stdout:
        return "", ""
    return extract_page_publish_date(result.stdout)


def rebuild_website_taxonomy(website):
    """Apply shared filtering and stable categories to already-scanned pages."""
    articles = website.get("articles", [])
    non_content_slugs = set()

    for article in articles:
        category, subcategory = categorize_article(article)
        article["bc"] = [category]
        article["sc"] = {category: [subcategory]} if subcategory else {}
        if is_non_content_path(urlparse(article.get("u", "")).path):
            non_content_slugs.add(article.get("s", ""))
            article["hidden"] = True
            article.pop("pending", None)

    approved = set(website.get("approved_slugs", [])) - non_content_slugs
    excluded = set(website.get("excluded_slugs", [])) | non_content_slugs
    website["approved_slugs"] = sorted(approved)
    website["excluded_slugs"] = sorted(excluded)

    visible = [
        article
        for article in articles
        if not article.get("hidden", False) and not article.get("pending", False)
    ]

    bc_counts = {}
    sc_counts = {}
    cat_hierarchy = {}
    for article in visible:
        for category in article.get("bc", []):
            bc_counts[category] = bc_counts.get(category, 0) + 1
        for category, subcategories in (article.get("sc", {}) or {}).items():
            cat_hierarchy.setdefault(category, {"subcats": []})
            for subcategory in subcategories:
                if subcategory and subcategory not in cat_hierarchy[category]["subcats"]:
                    cat_hierarchy[category]["subcats"].append(subcategory)
                key = f"{category}::{subcategory}"
                sc_counts[key] = sc_counts.get(key, 0) + 1

    sc_struct = {}
    for category, info in cat_hierarchy.items():
        sc_struct[category] = {}
        for subcategory in info["subcats"]:
            key = f"{category}::{subcategory}"
            sc_struct[category][subcategory] = sc_counts.get(key, 0)

    website["bc"] = bc_counts
    website["sc"] = sc_struct
    website["tag_freq"] = sc_counts
    website["cat_hierarchy"] = cat_hierarchy
    return visible


def clear_dark_thumbnails(visible):
    """Dark scraped hero images read as empty black cards in the grid."""
    if Image is None or ImageStat is None:
        return 0
    cleared = 0
    for article in visible:
        thumb = article.get("th", "")
        if not thumb.startswith("content/"):
            continue
        path = Path(ROOT) / thumb
        if not path.is_file():
            continue
        try:
            with Image.open(path) as image:
                brightness = ImageStat.Stat(image.convert("L")).mean[0]
        except Exception:
            continue
        if brightness < 25:
            article["th"] = ""
            cleared += 1
    return cleared


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--no-remote", action="store_true")
    args = parser.parse_args()

    with open(WEBSITE_PATH, encoding="utf-8") as f:
        website = json.load(f)

    articles = website.get("articles", [])
    visible = rebuild_website_taxonomy(website)
    dark_thumbnails = clear_dark_thumbnails(visible)
    cache = load_cache()
    local_count = 0

    for article in articles:
        slug = article.get("s", "")
        cached_date = normalize_date(cache.get(slug, {}).get("date", ""))
        if cached_date:
            article["pd"] = cached_date
            continue
        if article.get("pd"):
            cache[slug] = {"date": article["pd"], "source": "existing"}
            continue
        date, source = local_date(article)
        if date:
            article["pd"] = date
            cache[slug] = {"date": date, "source": source}
            local_count += 1

    remote_candidates = []
    for article in visible:
        if article.get("pd"):
            continue
        url = article.get("u", "")
        if not url or NON_ENGLISH_URL_RE.search(url):
            continue
        remote_candidates.append(article)

    remote_count = 0
    failures = []
    if remote_candidates and not args.no_remote:
        print(f"Fetching page metadata for {len(remote_candidates)} pages...", flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(remote_date, article, args.timeout, args.retries): article
                for article in remote_candidates
            }
            for done_count, future in enumerate(concurrent.futures.as_completed(futures), 1):
                article = futures[future]
                try:
                    date, source = future.result()
                except Exception:
                    date, source = "", ""
                if date:
                    article["pd"] = date
                    cache[article["s"]] = {"date": date, "source": source}
                    remote_count += 1
                else:
                    failures.append(article.get("s", ""))
                if done_count % 25 == 0 or done_count == len(futures):
                    print(f"  {done_count}/{len(futures)} remote pages checked", flush=True)
                    write_json(CACHE_PATH, dict(sorted(cache.items())))

    visible_with_date = sum(bool(article.get("pd")) for article in visible)
    website["dt"] = build_date_counts(visible)
    website["tag_zh"] = TAG_ZH

    used_tags = {
        sub
        for article in articles
        for subs in (article.get("sc", {}) or {}).values()
        for sub in subs
    }
    missing_tags = sorted(used_tags - set(TAG_ZH))
    if missing_tags:
        raise SystemExit("Missing website tag translations: " + ", ".join(missing_tags))

    write_json(WEBSITE_PATH, website)
    write_json(CACHE_PATH, dict(sorted(cache.items())))

    print(
        f"Publication dates: {visible_with_date}/{len(visible)} visible pages "
        f"(local {local_count}, remote {remote_count}, "
        f"missing {len(visible) - visible_with_date})."
    )
    if dark_thumbnails:
        print(f"Cleared {dark_thumbnails} dark card thumbnails.")
    if failures:
        print("Remote fetch failed for: " + ", ".join(sorted(failures)[:30]))
    print(
        f"Backfilled metadata for {len(articles)} website pages "
        f"and {len(TAG_ZH)} tag translations."
    )


if __name__ == "__main__":
    main()
