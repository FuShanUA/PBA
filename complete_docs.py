#!/usr/bin/env python3
"""Discover and fill the Palantir docs archive from all available sources."""

import argparse
import json
import os
import re
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))
CONTENT_DIR = os.path.join(ROOT, "content", "docs")
SITEMAP_PATH = os.path.join(ROOT, "data", "docs_sitemap.xml")
NAV_PATH = os.path.join(ROOT, "data", "docs_nav_tree.json")
CONTENT_SELECTOR = "div.ptcom-design__markdownDoc__1uarhel"
PRODUCT_PREFIXES = ("/docs/foundry/", "/docs/apollo/", "/docs/gotham/")
EXCLUDED_PATHS = {
    "/docs/foundry/",
    "/docs/apollo/",
    "/docs/gotham/",
    "/docs/foundry/search/",
    "/docs/apollo/search/",
    "/docs/gotham/search/",
}
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_local = threading.local()


def get_session():
    session = getattr(_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        _local.session = session
    return session


def canonical_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    host = "www.palantir.com" if parsed.netloc in ("palantir.com", "www.palantir.com") else parsed.netloc
    path = parsed.path or "/"
    path = path.rstrip("/") + "/"
    return f"https://{host}{path}"


def is_docs_page(url):
    parsed = urlparse(url)
    return (
        parsed.netloc in ("palantir.com", "www.palantir.com")
        and parsed.path.startswith(PRODUCT_PREFIXES)
        and parsed.path not in EXCLUDED_PATHS
    )


def slug_for(url):
    path = urlparse(url).path
    return path.removeprefix("/docs/").rstrip("/").replace("/", "-")


def build_reader_html(title, content_html, lang="en"):
    lang_attr = "zh-CN" if lang == "zh" else "en"
    return f'''<!DOCTYPE html>
<html lang="{lang_attr}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:760px;margin:0 auto;padding:40px 20px;line-height:1.7;color:#242424}}
h1{{font-size:1.8em;margin-bottom:8px}}
h2{{font-size:1.4em;margin-top:24px}}
h3{{font-size:1.2em;margin-top:20px}}
img{{max-width:100%;height:auto;border-radius:8px}}
pre{{overflow-x:auto;background:#f5f5f5;padding:16px;border-radius:8px}}
code{{background:#f5f5f5;padding:2px 6px;border-radius:4px;font-size:0.9em}}
a{{color:#1a8917}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ddd;padding:8px;text-align:left}}
</style>
</head>
<body>
<article>
{content_html}
</article>
</body>
</html>'''


def parse_sitemap():
    with open(SITEMAP_PATH, encoding="utf-8") as f:
        xml = f.read()
    urls = []
    for raw in re.findall(r"<loc>(https?://[^<]+)</loc>", xml):
        parsed = urlparse(raw)
        path = parsed.path
        # Language-specific sitemap entries are used only to discover the
        # canonical English URL; the Chinese page itself is never fetched.
        if path.startswith("/docs/zh/"):
            path = path.replace("/docs/zh/", "/docs/", 1)
        elif path.startswith(("/docs/jp/", "/docs/kr/")):
            continue
        urls.append(canonical_url(f"https://www.palantir.com{path}"))
    return {u for u in urls if u and is_docs_page(u)}


def parse_nav_tree():
    if not os.path.exists(NAV_PATH):
        return set()
    with open(NAV_PATH, encoding="utf-8") as f:
        pages = json.load(f)
    urls = {canonical_url(p.get("url", "")) for p in pages}
    return {u for u in urls if u and is_docs_page(u)}


def existing_pages():
    pages = {}
    for slug in os.listdir(CONTENT_DIR):
        meta_path = os.path.join(CONTENT_DIR, slug, "meta.json")
        page_path = os.path.join(CONTENT_DIR, slug, "page.html")
        if not os.path.isfile(meta_path) or not os.path.isfile(page_path):
            continue
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        url = canonical_url(meta.get("url", ""))
        if url and is_docs_page(url) and slug_for(url) == slug:
            pages[url] = slug
    return pages


def links_in_file(path, base_url):
    try:
        with open(path, encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "lxml")
    except Exception:
        return set()
    found = set()
    for link in soup.select("a[href]"):
        raw = link.get("href", "")
        if not raw or raw.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        target = canonical_url(urljoin(base_url, raw))
        if target and is_docs_page(target):
            found.add(target)
    return found


def links_in_local_pages(pages):
    found = set()
    for url, slug in pages.items():
        for filename in ("page.html", "page_zh.html"):
            path = os.path.join(CONTENT_DIR, slug, filename)
            if os.path.isfile(path):
                found.update(links_in_file(path, url))
    return {u for u in found if is_docs_page(u)}


def extract_content(html):
    soup = BeautifulSoup(html, "lxml")
    el = soup.select_one(CONTENT_SELECTOR)
    if not el:
        return None, None
    title = el.select_one("h1")
    title_text = title.get_text(" ", strip=True) if title else soup.title.get_text(" ", strip=True)
    if not title_text or "Page Not Found" in title_text:
        return None, None
    return title_text, str(el)


def fetch_page(url):
    response = get_session().get(url, timeout=45)
    response.raise_for_status()
    response.encoding = "utf-8"
    return extract_content(response.text)


def save_page(url, title, content, lang):
    slug = slug_for(url)
    page_dir = os.path.join(CONTENT_DIR, slug)
    os.makedirs(page_dir, exist_ok=True)
    filename = "page_zh.html" if lang == "zh" else "page.html"
    with open(os.path.join(page_dir, filename), "w", encoding="utf-8") as f:
        f.write(build_reader_html(title, content, lang))
    if lang == "en":
        with open(os.path.join(page_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump({"slug": slug, "url": url}, f, ensure_ascii=False, indent=2)
            f.write("\n")
    return slug


def scrape_url(url):
    result = {"url": url, "status": "error"}
    try:
        title, content = fetch_page(url)
        if not content:
            result["status"] = "no-content"
            return result
        result["slug"] = save_page(url, title, content, "en")
        result["status"] = "ok"
    except Exception as exc:
        result["status"] = f"error: {str(exc)[:80]}"
    return result


def scrape_missing(queue, existing, workers):
    todo = deque(sorted(u for u in queue if u not in existing))
    scraped = {}
    failures = []

    while todo:
        batch = [todo.popleft() for _ in range(min(workers, len(todo)))]
        with ThreadPoolExecutor(max_workers=len(batch)) as executor:
            futures = {executor.submit(scrape_url, url): url for url in batch}
            for future in as_completed(futures):
                url = futures[future]
                result = future.result()
                if result["status"] == "ok":
                    scraped[url] = result
                    existing[url] = result["slug"]
                    print(f"  ok {len(existing)} {result['slug']}", flush=True)
                else:
                    failures.append((url, result["status"]))
                    print(f"  {result['status']} {url}", flush=True)
        time.sleep(0.15)

    return scraped, failures


def write_manifest(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    os.makedirs(CONTENT_DIR, exist_ok=True)
    sitemap = parse_sitemap()
    nav = parse_nav_tree()
    existing = existing_pages()
    linked = links_in_local_pages(existing)
    seeds = sitemap | nav | linked
    missing = sorted(u for u in seeds if u not in existing)

    print(f"Sources: sitemap={len(sitemap)} nav={len(nav)} local={len(existing)} linked={len(linked)}", flush=True)
    print(f"Union: {len(seeds)} pages; missing before closure: {len(missing)}", flush=True)
    if args.dry_run:
        write_manifest(os.path.join(ROOT, "data", "docs_missing.json"), {"missing": missing})
        for url in missing[:30]:
            print(f"  {url}")
        return

    scraped, failures = scrape_missing(seeds, existing, args.workers)

    # One closure pass catches links that only appeared on newly fetched pages.
    new_links = links_in_local_pages(existing)
    second_queue = {u for u in new_links if u not in existing}
    if second_queue:
        print(f"Closure pass: {len(second_queue)} newly discovered pages", flush=True)
        more_scraped, more_failures = scrape_missing(second_queue, existing, args.workers)
        scraped.update(more_scraped)
        failures.extend(more_failures)

    untranslated = []
    for url in sorted(existing):
        zh_path = os.path.join(CONTENT_DIR, existing[url], "page_zh.html")
        if not os.path.isfile(zh_path) or os.path.getsize(zh_path) < 200:
            untranslated.append(url)

    write_manifest(
        os.path.join(ROOT, "data", "docs_completion.json"),
        {
            "sitemap": len(sitemap),
            "nav": len(nav),
            "local": len(existing),
            "linked": len(new_links),
            "scraped": len(scraped),
            "failures": failures,
            "untranslated": untranslated,
        },
    )
    print(f"Done: local={len(existing)} scraped={len(scraped)} failures={len(failures)} untranslated={len(untranslated)}", flush=True)


if __name__ == "__main__":
    main()
