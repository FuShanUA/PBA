#!/usr/bin/env python3
"""Scraper for Palantir official website (palantir.com).
Uses manifest-based incremental scanning: only fetches new/changed pages.
Excludes /blog/ and /docs/ (covered by other sources)."""

import re, json, os, time, hashlib, sys
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, unquote

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

try:
    from .website_tags import TAG_ZH
    from .website_dates import build_date_counts, extract_page_publish_date
    from .website_taxonomy import categorize_url, is_non_content_path, is_non_english_url, should_exclude
except ImportError:
    from website_tags import TAG_ZH
    from website_dates import build_date_counts, extract_page_publish_date
    from website_taxonomy import categorize_url, is_non_content_path, is_non_english_url, should_exclude

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT_DIR = os.path.join(ROOT, "content", "website")
MANIFEST_PATH = os.path.join(ROOT, "data", "website_manifest.json")
OUTPUT_PATH = os.path.join(ROOT, "data", "sources", "website.json")
SUMMARY_PATH = os.path.join(ROOT, "data", "website_update_summary.json")
TITLE_ZH_PATH = os.path.join(ROOT, "data", "website_title_zh.json")
BASE_URL = "https://www.palantir.com"
CONTENT_HASH_VERSION = 2

SECTION_ROOTS = [
    "platforms", "offerings", "impact", "about", "pcl", "careers", "newsroom",
    "information-security", "partnerships", "customer-success-services",
    "insights", "foundation", "explore", "aip", "devcon",
]

def load_manifest():
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"source": "website", "last_scan": "", "entries": {}}

def save_manifest(manifest):
    manifest["last_scan"] = datetime.now(timezone.utc).isoformat()
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

def discover_urls(page):
    """Crawl the sitemap and section pages to discover all URLs."""
    discovered = set()

    # Try sitemap first
    print("  Trying sitemap...", flush=True)
    try:
        page.goto(f"{BASE_URL}/sitemap.xml", wait_until="domcontentloaded", timeout=15000)
        time.sleep(2)
        content = page.content()
        urls = re.findall(r'<loc>(https://www\.palantir\.com/[^<]+)</loc>', content)
        for url in urls:
            path = urlparse(url).path
            if (
                not should_exclude(path)
                and not is_non_english_url(path)
                and path != "/"
            ):
                discovered.add(url)
        print(f"    Sitemap: {len(discovered)} URLs", flush=True)
    except:
        print("    Sitemap failed, using section crawl", flush=True)

    # Also crawl each section page for links
    for section in SECTION_ROOTS:
        url = f"{BASE_URL}/{section}/"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)
            links = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
            for href in links:
                parsed = urlparse(href)
                if parsed.netloc == "www.palantir.com":
                    path = parsed.path
                    if (
                        not should_exclude(path)
                        and not is_non_english_url(path)
                        and path != "/"
                        and len(path) > 1
                    ):
                        full_url = f"{BASE_URL}{path}"
                        discovered.add(full_url)
        except:
            pass
    
    return discovered

def wait_for_rendered_content(page):
    """Wait for Palantir's client-rendered pages to finish hydrating."""
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    try:
        page.wait_for_function(
            "document.body && document.body.innerText.trim().length >= 200",
            timeout=10000,
        )
    except Exception:
        pass
    page.wait_for_timeout(500)

def build_stable_content_hash(html):
    """Hash visible content, excluding widgets and values that change per load."""
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("main") or soup.find("body") or soup
    for node in content.select("iframe,textarea,script,style,noscript,template"):
        node.decompose()
    for tag in content.find_all(True):
        for attr in ("style", "src", "srcset", "data-src", "data-srcset"):
            tag.attrs.pop(attr, None)
    text = " ".join(content.get_text(" ").split())
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]

def extract_page_data(html, url):
    """Extract title, description, og:image from page HTML."""
    title_m = re.search(r'<title[^>]*>([^<]+)</title>', html, re.I)
    title = title_m.group(1).strip() if title_m else ""
    title = re.sub(r'\s*[\|–-]\s*Palantir.*$', '', title).strip()
    
    desc_m = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', html, re.I)
    if not desc_m:
        desc_m = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"', html, re.I)
    desc = desc_m.group(1).strip() if desc_m else ""
    
    img_m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html, re.I)
    thumb = img_m.group(1).replace("&amp;", "&") if img_m else ""
    
    # Extract main content
    content_m = re.search(r'<main[^>]*>(.*?)</main>', html, re.DOTALL | re.I)
    if not content_m:
        content_m = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.I)
    content_html = content_m.group(1).strip() if content_m else html
    published_date, published_date_source = extract_page_publish_date(
        html, content_html
    )

    return {
        "title": title,
        "desc": desc,
        "thumb": thumb,
        "content_html": content_html,
        "published_date": published_date,
        "published_date_source": published_date_source,
    }

def build_page_html(title, content_html, url):
    """Build a self-contained reader HTML for the page."""
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:760px;margin:0 auto;padding:40px 20px;line-height:1.7;color:#242424}}
h1{{font-size:1.8em;margin-bottom:8px}}
img{{max-width:100%;height:auto;border-radius:8px}}
pre{{overflow-x:auto;background:#f5f5f5;padding:16px;border-radius:8px}}
a{{color:#1a8917}}
</style>
</head>
<body>
<article>
{content_html}
</article>
</body>
</html>'''

def absolutize_page_urls(content_html):
    """Make media and site links work from the local archive server."""
    soup = BeautifulSoup(content_html, "html.parser")
    for node in soup.select("section[id$='-form']"):
        node.decompose()
    for form in list(soup.find_all("form")):
        section = form.find_parent("section")
        if section and section.get("id", "").endswith("-form"):
            section.decompose()
        else:
            form.decompose()
    for tag in soup.find_all(True):
        style = tag.get("style")
        if not isinstance(style, str):
            continue
        declarations = [part.strip() for part in style.split(";") if part.strip()]
        retained = [
            part
            for part in declarations
            if not part.lower().startswith("opacity:")
            and not part.lower().startswith("transform:")
        ]
        if retained:
            tag["style"] = "; ".join(retained)
        else:
            del tag["style"]
    for tag in soup.find_all(True):
        for attr in ("src", "href", "poster", "data-src"):
            value = tag.get(attr)
            if not isinstance(value, str):
                continue
            if value.startswith("//"):
                tag[attr] = "https:" + value
            elif value.startswith("/"):
                tag[attr] = BASE_URL + value
        for attr in ("srcset", "data-srcset"):
            value = tag.get(attr)
            if not isinstance(value, str):
                continue
            candidates = []
            for candidate in value.split(","):
                parts = candidate.strip().split()
                if not parts:
                    continue
                url = parts[0]
                if url.startswith("//"):
                    url = "https:" + url
                elif url.startswith("/"):
                    url = BASE_URL + url
                candidates.append(" ".join([url, *parts[1:]]))
            tag[attr] = ", ".join(candidates)
    return str(soup)

def scrape_page(page, url, manifest):
    """Scrape a single page. Returns article metadata dict or None."""
    path = urlparse(url).path
    slug = path.strip("/").replace("/", "-") or "home"
    
    # Check manifest for incremental skip
    entry = manifest["entries"].get(slug)
    if entry and entry.get("status") == "ok":
        # Check if content changed
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            wait_for_rendered_content(page)
            html = page.content()
            content_hash = build_stable_content_hash(html)
            if (
                entry.get("content_hash_version") == CONTENT_HASH_VERSION
                and content_hash == entry.get("content_hash")
            ):
                entry["last_checked"] = datetime.now(timezone.utc).isoformat()
                return "skip", slug
        except:
            entry["last_checked"] = datetime.now(timezone.utc).isoformat()
            return "skip", slug
    
    # Fetch the page
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        wait_for_rendered_content(page)
        html = page.content()
        content_hash = build_stable_content_hash(html)
    except Exception as e:
        return f"error:{str(e)[:50]}", slug
    
    data = extract_page_data(html, url)
    if not data["title"]:
        return "error:notitle", slug
    
    category, subcategory = categorize_url(path)
    
    # Save content
    os.makedirs(os.path.join(CONTENT_DIR, slug), exist_ok=True)
    reader_path = os.path.join(CONTENT_DIR, slug, "page.html")
    with open(reader_path, "w", encoding="utf-8") as f:
        f.write(
            build_page_html(
                data["title"],
                absolutize_page_urls(data["content_html"]),
                url,
            )
        )
    
    # Take screenshot for card thumbnail if no og:image
    if not data["thumb"]:
        try:
            ss_path = os.path.join(CONTENT_DIR, slug, "screenshot.png")
            page.screenshot(path=ss_path, full_page=False)
            data["thumb"] = f"content/website/{slug}/screenshot.png"
        except:
            pass
    
    # Build article entry
    now = datetime.now(timezone.utc).isoformat()
    first_scanned = (
        entry.get("first_scanned", now)
        if entry
        else now
    )
    article = {
        "t": data["title"],
        "tt": data["title"],  # Will be translated later
        "d": first_scanned[:10],
        "ud": now[:10],
        "pd": data["published_date"],
        "s": slug,
        "u": url,
        "bc": [category],
        "sc": {category: [subcategory]} if subcategory else {},
        "th": data["thumb"],
        "ds": data["desc"],
        "sn": data["desc"][:150] if data["desc"] else "",
        "hp": f"content/website/{slug}/page.html",
    }
    
    # Update manifest
    manifest["entries"][slug] = {
        "url": url,
        "first_scanned": first_scanned,
        "last_checked": now,
        "content_updated": now,
        "content_hash": content_hash,
        "content_hash_version": CONTENT_HASH_VERSION,
        "published_date": data["published_date"],
        "published_date_source": data["published_date_source"],
        "status": "ok",
    }
    
    return article, slug

def main():
    incremental = "--full" not in sys.argv
    only_arg = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--only" and i < len(sys.argv):
            only_arg = sys.argv[i + 1]
            break
    
    manifest = load_manifest()
    print(f"Website scraper - mode: {'incremental' if incremental else 'full'}", flush=True)
    print(f"Manifest entries: {len(manifest['entries'])}", flush=True)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        if only_arg:
            requested = {item.strip() for item in only_arg.split(",") if item.strip()}
            check_urls = [
                entry["url"]
                for slug, entry in sorted(manifest["entries"].items())
                if slug in requested or entry.get("url") in requested
            ]
            known_slugs = {slug for slug in manifest["entries"] if slug in requested}
            known_urls = {entry.get("url") for entry in manifest["entries"].values()}
            missing = requested - known_slugs - known_urls
            if missing:
                raise SystemExit(f"Unknown --only values: {', '.join(sorted(missing))}")
            print(f"\n=== Phase 1: Targeted refresh ({len(check_urls)} pages) ===", flush=True)
        else:
            # Phase 1: Discover URLs
            print("\n=== Phase 1: Discovery ===", flush=True)
            discovered = discover_urls(page)
            print(f"Discovered {len(discovered)} candidate URLs (not all new)", flush=True)
            check_urls = sorted(discovered)
        
        # Existing pages are checked too so content changes are detected.
        if incremental:
            print(f"Checking {len(check_urls)} candidates against the manifest", flush=True)
        
        # Phase 2: Scrape
        print(f"\n=== Phase 2: Checking {len(check_urls)} candidates ===", flush=True)
        old_by_slug = {}
        if os.path.exists(OUTPUT_PATH):
            try:
                with open(OUTPUT_PATH, encoding="utf-8") as f:
                    old_data = json.load(f)
                old_by_slug = {a.get("s"): a for a in old_data.get("articles", [])}
            except Exception:
                old_by_slug = {}

        articles = []
        new_slugs = []
        changed_slugs = []
        ok = 0
        skip = 0
        err = 0

        # Keep pages that are no longer in the sitemap, but are still valid archive pages.
        existing_articles = []
        for slug, entry in manifest["entries"].items():
            if entry.get("status") != "ok":
                continue
            reader_path = os.path.join(CONTENT_DIR, slug, "page.html")
            if not os.path.exists(reader_path):
                continue
            if slug in old_by_slug:
                article = dict(old_by_slug[slug])
                article["d"] = entry.get("first_scanned", article.get("d", ""))[:10]
                article["ud"] = entry.get("last_checked", entry.get("first_scanned", ""))[:10]
                if not article.get("pd") and entry.get("published_date"):
                    article["pd"] = entry["published_date"]
                existing_articles.append(article)
                continue

            path = urlparse(entry["url"]).path
            category, subcategory = categorize_url(path)
            with open(reader_path, encoding="utf-8") as f:
                reader_html = f.read()
            title_m = re.search(r'<title>([^<]+)</title>', reader_html)
            title = title_m.group(1).strip() if title_m else slug
            existing_articles.append({
                "t": title,
                "tt": title,
                "d": entry.get("first_scanned", "")[:10],
                "ud": entry.get("last_checked", entry.get("first_scanned", ""))[:10],
                "pd": entry.get("published_date", ""),
                "s": slug,
                "u": entry["url"],
                "bc": [category],
                "sc": {category: [subcategory]} if subcategory else {},
                "th": "",
                "ds": "",
                "sn": "",
                "hp": f"content/website/{slug}/page.html",
            })

        for i, url in enumerate(check_urls):
            path = urlparse(url).path
            slug = path.strip("/").replace("/", "-") or "home"
            print(f"  [{i+1}/{len(check_urls)}] {slug[:50]}", flush=True)
            
            result, slug = scrape_page(page, url, manifest)
            
            if result == "skip":
                skip += 1
            elif isinstance(result, dict):
                is_changed = slug in old_by_slug
                article = dict(old_by_slug.get(slug, {}))
                article.update(result)
                old_article = old_by_slug.get(slug, {})
                for field in ("tt", "th", "ds", "sn"):
                    if old_article.get(field):
                        article[field] = old_article[field]
                if is_changed:
                    changed_slugs.append(slug)
                else:
                    new_slugs.append(slug)
                if not article.get("pd") and old_article.get("pd"):
                    article["pd"] = old_article["pd"]
                articles.append(article)
                ok += 1
                print(f"    OK: {result['t'][:50]}", flush=True)
            else:
                err += 1
                print(f"    {result}", flush=True)
        
        browser.close()
    
    # Phase 3: Save
    print(f"\n=== Phase 3: Saving ===", flush=True)
    save_manifest(manifest)
    
    article_by_slug = {a["s"]: a for a in existing_articles}
    for article in articles:
        article_by_slug[article["s"]] = article
    unique = [article_by_slug[slug] for slug in sorted(article_by_slug)]

    title_zh = {}
    if os.path.exists(TITLE_ZH_PATH):
        with open(TITLE_ZH_PATH, encoding="utf-8") as f:
            title_zh = json.load(f)
    for article in unique:
        if title_zh.get(article.get("s")):
            article["tt"] = title_zh[article["s"]]

    # Recompute taxonomy and review lists. Non-content pages are always hidden,
    # while user exclusions of real content pages remain intact.
    old_approved = set()
    old_excluded = set()
    if os.path.exists(OUTPUT_PATH):
        try:
            with open(OUTPUT_PATH, encoding="utf-8") as f:
                old = json.load(f)
            old_approved = set(old.get("approved_slugs", []))
            old_excluded = set(old.get("excluded_slugs", []))
        except Exception:
            pass

    non_content_slugs = set()
    for article in unique:
        path = urlparse(article.get("u", "")).path
        category, subcategory = categorize_url(path)
        article["bc"] = [category]
        article["sc"] = {category: [subcategory]} if subcategory else {}
        title = article.get("t", "")
        is_not_found = "page not found" in title.lower() or title.startswith("404")
        if is_non_content_path(path) or is_not_found:
            non_content_slugs.add(article["s"])
            article["hidden"] = True
            article.pop("pending", None)

    approved_slugs = old_approved - non_content_slugs
    excluded_slugs = old_excluded | non_content_slugs

    visible_articles = [
        article for article in unique
        if not article.get("hidden", False) and not article.get("pending", False)
    ]

    # Build category hierarchy from visible content only.
    bc_counts = {}
    sc_counts = {}
    cat_hierarchy = {}
    for a in visible_articles:
        for cat in a.get("bc", []):
            bc_counts[cat] = bc_counts.get(cat, 0) + 1
        for cat, subs in a.get("sc", {}).items():
            if cat not in cat_hierarchy:
                cat_hierarchy[cat] = {"subcats": []}
            for sub in subs:
                if sub and sub not in cat_hierarchy[cat]["subcats"]:
                    cat_hierarchy[cat]["subcats"].append(sub)
                key = f"{cat}::{sub}"
                sc_counts[key] = sc_counts.get(key, 0) + 1
    
    sc_struct = {}
    for cat, info in cat_hierarchy.items():
        sc_struct[cat] = {}
        for sub in info["subcats"]:
            key = f"{cat}::{sub}"
            sc_struct[cat][sub] = sc_counts.get(key, 0)
    
    output = {
        "source": "website",
        "source_name": "Palantir Website",
        "source_name_zh": "Palantir 官网",
        "last_scan": datetime.now(timezone.utc).isoformat(),
        "articles": unique,
        "bc": bc_counts,
        "sc": sc_struct,
        "dt": build_date_counts(visible_articles),
        "tag_freq": sc_counts,
        "cat_hierarchy": cat_hierarchy,
        "tag_zh": TAG_ZH,
    }
    
    output["approved_slugs"] = sorted(approved_slugs)
    output["excluded_slugs"] = sorted(excluded_slugs)
    
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    summary = {
        "new": len(new_slugs),
        "changed": len(changed_slugs),
        "skipped": skip,
        "errors": err,
        "new_slugs": new_slugs,
        "changed_slugs": changed_slugs,
        "has_updates": bool(new_slugs or changed_slugs),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
        f.write("\n")
    
    print(f"\n=== Done! ===")
    print(f"  New: {len(new_slugs)}, Changed: {len(changed_slugs)}, Skipped: {skip}, Errors: {err}")
    print(f"  Total website articles: {len(unique)}")
    print(f"  Saved to: {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
