#!/usr/bin/env python3
"""Generate data/sources/docs.json from content/docs/ directory."""

import json, os, re
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
CONTENT_DIR = os.path.join(ROOT, "content", "docs")
OUTPUT = os.path.join(ROOT, "data", "sources", "docs.json")

def extract_h1(html):
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
    if m:
        return re.sub(r'<[^>]+>', '', m.group(1)).strip()
    return None

def categorize(url_path):
    clean = url_path.replace("/docs/", "").strip("/")
    parts = [p for p in clean.split("/") if p]
    product = parts[0] if parts else "foundry"
    section = parts[1] if len(parts) > 1 else ""
    page = parts[-1] if parts else ""
    cat = "Documentation"
    sub_parts = [product]
    if section and section != page:
        sub_parts.append(section)
    sub = " > ".join(sub_parts)
    return cat, [sub]

def main():
    articles = []
    for slug in sorted(os.listdir(CONTENT_DIR)):
        page_dir = os.path.join(CONTENT_DIR, slug)
        if not os.path.isdir(page_dir):
            continue
        en_path = os.path.join(page_dir, "page.html")
        zh_path = os.path.join(page_dir, "page_zh.html")
        if not os.path.exists(en_path):
            continue
        with open(en_path, "r", encoding="utf-8") as f:
            en_html = f.read()
        title = extract_h1(en_html) or slug
        zh_title = title
        if os.path.exists(zh_path):
            with open(zh_path, "r", encoding="utf-8") as f:
                zh_html = f.read()
            zh_h1 = extract_h1(zh_html)
            if zh_h1:
                zh_title = zh_h1
        meta_path = os.path.join(page_dir, "meta.json")
        url = ""
        url_path = ""
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            url = meta.get("url", "")
            url_path = url.replace("https://www.palantir.com", "")
        else:
            url_path = "/docs/" + slug.replace("-", "/") + "/"
            url = f"https://www.palantir.com{url_path}"
        cat, subcats = categorize(url_path)
        desc = ""
        m = re.search(r'<p[^>]*>(.*?)</p>', en_html, re.DOTALL)
        if m:
            desc = re.sub(r'<[^>]+>', '', m.group(1)).strip()[:150]
        # Only include if we have a zh translation
        has_zh = os.path.exists(zh_path) and os.path.getsize(zh_path) > 200
        article = {
            "t": title,
            "tt": zh_title if has_zh else title,
            "d": "",
            "s": slug,
            "u": url,
            "bc": [cat],
            "sc": {cat: subcats},
            "th": "",
            "ds": desc,
            "sn": desc[:150] if desc else "",
            "hp": f"content/docs/{slug}/page.html",
        }
        articles.append(article)

    bc_counts = {}
    sc_counts = {}
    cat_hierarchy = {}
    for a in articles:
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
        "source": "docs",
        "source_name": "Palantir Documentation",
        "source_name_zh": "Palantir 文档",
        "last_scan": datetime.now(timezone.utc).isoformat(),
        "articles": articles,
        "bc": bc_counts,
        "sc": sc_struct,
        "dt": {},
        "tag_freq": sc_counts,
        "cat_hierarchy": cat_hierarchy,
    }
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Generated {OUTPUT}: {len(articles)} articles")

if __name__ == "__main__":
    main()
