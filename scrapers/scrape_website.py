#!/usr/bin/env python3
"""Scraper for Palantir official website (palantir.com).
Uses manifest-based incremental scanning: only fetches new/changed pages.
Excludes /blog/ and /docs/ (covered by other sources)."""

import re, json, os, time, hashlib, sys
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, unquote
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT_DIR = os.path.join(ROOT, "content", "website")
MANIFEST_PATH = os.path.join(ROOT, "data", "website_manifest.json")
OUTPUT_PATH = os.path.join(ROOT, "data", "sources", "website.json")
BASE_URL = "https://www.palantir.com"

# Sections to crawl and their category mappings
SECTIONS = {
    "platforms": {"category": "Platforms", "category_zh": "平台"},
    "offerings": {"category": "Offerings", "category_zh": "行业方案"},
    "impact": {"category": "Impact Studies", "category_zh": "客户案例"},
    "about": {"category": "About", "category_zh": "关于"},
    "pcl": {"category": "Privacy & Civil Liberties", "category_zh": "隐私与公民自由"},
    "careers": {"category": "Careers", "category_zh": "招聘"},
    "newsroom": {"category": "Newsroom", "category_zh": "新闻"},
    "information-security": {"category": "Information Security", "category_zh": "信息安全"},
    "partnerships": {"category": "Partnerships", "category_zh": "合作伙伴"},
    "customer-success-services": {"category": "Customer Success", "category_zh": "客户成功"},
}

# Special product pages (not under standard sections)
SPECIAL_PAGES = {
    "alpha": {"category": "Special Products", "category_zh": "特殊产品"},
    "warpspeed": {"category": "Special Products", "category_zh": "特殊产品"},
    "shipos": {"category": "Special Products", "category_zh": "特殊产品"},
    "titan": {"category": "Special Products", "category_zh": "特殊产品"},
    "chain-reaction": {"category": "Special Products", "category_zh": "特殊产品"},
    "mission-manager": {"category": "Special Products", "category_zh": "特殊产品"},
    "migration": {"category": "Special Products", "category_zh": "特殊产品"},
    "interoperability": {"category": "Special Products", "category_zh": "特殊产品"},
    "palantir-explained": {"category": "Palantir Explained", "category_zh": "Palantir 解析"},
}

EXCLUDE_PREFIXES = [
    "/blog", "/docs", "/sitemap", "/cookie", "/terms", "/privacy-and-security",
    "/human-rights", "/modern-slavery", "/store", "/contact", "/jp", "/uk",
    "/us-public-policy", "/responsible-business", "/q1-2026", "/news-details",
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

def should_exclude(path):
    return any(path.startswith(p) for p in EXCLUDE_PREFIXES)

def categorize_url(path):
    """Determine the section and subcategory from URL path."""
    parts = path.strip("/").split("/")
    if not parts or parts[0] == "":
        return "Home", "首页", ""
    
    top = parts[0]
    
    # Check special pages first
    if top in SPECIAL_PAGES:
        info = SPECIAL_PAGES[top]
        sub = parts[1] if len(parts) > 1 else ""
        return info["category"], info["category_zh"], sub
    
    # Check standard sections
    if top in SECTIONS:
        info = SECTIONS[top]
        sub = parts[1] if len(parts) > 1 else ""
        return info["category"], info["category_zh"], sub
    
    # Check if it's a platform sub-page
    if top == "aip" and len(parts) > 0:
        return "Platforms", "平台", "AIP"
    
    return "Other", "其他", top

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
            if not should_exclude(path) and path != "/":
                discovered.add(url)
        print(f"    Sitemap: {len(discovered)} URLs", flush=True)
    except:
        print("    Sitemap failed, using section crawl", flush=True)
    
    # Also crawl each section page for links
    for section in list(SECTIONS.keys()) + list(SPECIAL_PAGES.keys()):
        url = f"{BASE_URL}/{section}/"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)
            links = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
            for href in links:
                parsed = urlparse(href)
                if parsed.netloc == "www.palantir.com":
                    path = parsed.path
                    if not should_exclude(path) and path != "/" and len(path) > 1:
                        full_url = f"{BASE_URL}{path}"
                        discovered.add(full_url)
        except:
            pass
    
    return discovered

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
    
    return {"title": title, "desc": desc, "thumb": thumb, "content_html": content_html}

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
            time.sleep(2)
            html = page.content()
            content_hash = hashlib.md5(html.encode("utf-8")).hexdigest()[:12]
            if content_hash == entry.get("content_hash"):
                return "skip", slug
        except:
            return "skip", slug
    
    # Fetch the page
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        time.sleep(3)
        html = page.content()
        content_hash = hashlib.md5(html.encode("utf-8")).hexdigest()[:12]
    except Exception as e:
        return f"error:{str(e)[:50]}", slug
    
    data = extract_page_data(html, url)
    if not data["title"]:
        return "error:notitle", slug
    
    category, category_zh, subcategory = categorize_url(path)
    
    # Save content
    os.makedirs(os.path.join(CONTENT_DIR, slug), exist_ok=True)
    reader_path = os.path.join(CONTENT_DIR, slug, "page.html")
    with open(reader_path, "w", encoding="utf-8") as f:
        f.write(build_page_html(data["title"], data["content_html"], url))
    
    # Take screenshot for card thumbnail if no og:image
    if not data["thumb"]:
        try:
            ss_path = os.path.join(CONTENT_DIR, slug, "screenshot.png")
            page.screenshot(path=ss_path, full_page=False)
            data["thumb"] = f"content/website/{slug}/screenshot.png"
        except:
            pass
    
    # Build article entry
    article = {
        "t": data["title"],
        "tt": data["title"],  # Will be translated later
        "d": "",  # Website pages don't have natural dates
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
        "first_scanned": entry.get("first_scanned", datetime.now(timezone.utc).isoformat()) if entry else datetime.now(timezone.utc).isoformat(),
        "last_checked": datetime.now(timezone.utc).isoformat(),
        "content_hash": content_hash,
        "status": "ok",
    }
    
    return article, slug

def main():
    incremental = "--full" not in sys.argv
    
    manifest = load_manifest()
    print(f"Website scraper - mode: {'incremental' if incremental else 'full'}", flush=True)
    print(f"Manifest entries: {len(manifest['entries'])}", flush=True)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        
        # Phase 1: Discover URLs
        print("\n=== Phase 1: Discovery ===", flush=True)
        discovered = discover_urls(page)
        print(f"Discovered {len(discovered)} URLs", flush=True)
        
        # Filter out already-scanned URLs in incremental mode
        if incremental:
            new_urls = [u for u in discovered if urlparse(u).path.strip("/").replace("/", "-") not in manifest["entries"]]
            print(f"New URLs to scan: {len(new_urls)} (skipping {len(discovered) - len(new_urls)} existing)", flush=True)
        else:
            new_urls = list(discovered)
        
        # Phase 2: Scrape
        print(f"\n=== Phase 2: Scraping {len(new_urls)} pages ===", flush=True)
        articles = []
        ok = 0
        skip = 0
        err = 0
        
        # Also reload existing articles from manifest
        existing_articles = []
        for slug, entry in manifest["entries"].items():
            if entry.get("status") == "ok":
                reader_path = os.path.join(CONTENT_DIR, slug, "page.html")
                if os.path.exists(reader_path):
                    # Rebuild article from manifest + reader
                    path = urlparse(entry["url"]).path
                    category, category_zh, subcategory = categorize_url(path)
                    # Read title from the saved HTML
                    with open(reader_path, "r", encoding="utf-8") as f:
                        reader_html = f.read()
                    title_m = re.search(r'<title>([^<]+)</title>', reader_html)
                    title = title_m.group(1).strip() if title_m else slug
                    
                    existing_articles.append({
                        "t": title,
                        "tt": title,
                        "d": "",
                        "s": slug,
                        "u": entry["url"],
                        "bc": [category],
                        "sc": {category: [subcategory]} if subcategory else {},
                        "th": "",
                        "ds": "",
                        "sn": "",
                        "hp": f"content/website/{slug}/page.html",
                    })
        
        for i, url in enumerate(sorted(new_urls)):
            path = urlparse(url).path
            slug = path.strip("/").replace("/", "-") or "home"
            print(f"  [{i+1}/{len(new_urls)}] {slug[:50]}", flush=True)
            
            result, slug = scrape_page(page, url, manifest)
            
            if result == "skip":
                skip += 1
            elif isinstance(result, dict):
                articles.append(result)
                ok += 1
                print(f"    OK: {result['t'][:50]}", flush=True)
            else:
                err += 1
                print(f"    {result}", flush=True)
        
        browser.close()
    
    # Phase 3: Save
    print(f"\n=== Phase 3: Saving ===", flush=True)
    save_manifest(manifest)
    
    all_articles = existing_articles + articles
    # Deduplicate by slug
    seen = set()
    unique = []
    for a in all_articles:
        if a["s"] not in seen:
            seen.add(a["s"])
            unique.append(a)
    
    # Build category hierarchy
    bc_counts = {}
    sc_counts = {}
    cat_hierarchy = {}
    for a in unique:
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
        "dt": {},
        "tag_freq": sc_counts,
        "cat_hierarchy": cat_hierarchy,
    }
    
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n=== Done! ===")
    print(f"  New: {ok}, Skipped: {skip}, Errors: {err}")
    print(f"  Total website articles: {len(unique)}")
    print(f"  Saved to: {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
