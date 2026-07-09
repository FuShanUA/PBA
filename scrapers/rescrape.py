#!/usr/bin/env python3
"""Re-scrape missing docs pages with better content waiting."""

import sys, os, re, json, time
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT_DIR = os.path.join(ROOT, "content", "docs")
CONTENT_SELECTOR = "div.ptcom-design__markdownDoc__1uarhel"

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

def main():
    pages = json.load(open(os.path.join(ROOT, "data", "docs_nav_tree.json")))
    
    # Find missing pages (skip filter URLs with ?)
    todo = []
    for p in pages:
        slug = p['path'].replace('/docs/', '').rstrip('/').replace('/', '-')
        if '?' in slug:
            continue  # skip filter URLs
        en_path = os.path.join(CONTENT_DIR, slug, "page.html")
        if not (os.path.exists(en_path) and os.path.getsize(en_path) > 200):
            todo.append((slug, p['url']))
    
    print(f"[Rescrape] todo={len(todo)}", flush=True)
    if not todo:
        print("Nothing to scrape.", flush=True)
        return

    ok = err = 0
    BATCH_SIZE = 30
    
    for batch_start in range(0, len(todo), BATCH_SIZE):
        batch = todo[batch_start:batch_start + BATCH_SIZE]
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(ignore_https_errors=True, viewport={"width": 1280, "height": 900})
                page = context.new_page()
                for slug, url in batch:
                    page_dir = os.path.join(CONTENT_DIR, slug)
                    os.makedirs(page_dir, exist_ok=True)
                    try:
                        resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        if not resp or resp.status != 200:
                            err += 1
                            continue
                        # Wait for content element to appear (client-side rendering)
                        try:
                            page.wait_for_selector(CONTENT_SELECTOR, timeout=10000)
                        except Exception:
                            page.wait_for_timeout(3000)
                        
                        content_html = page.evaluate(f"""() => {{
                            const el = document.querySelector('{CONTENT_SELECTOR}');
                            return el ? el.innerHTML : '';
                        }}""")
                        if not content_html or len(content_html) < 50:
                            err += 1
                            continue
                        title = page.evaluate(f"""() => {{
                            const el = document.querySelector('{CONTENT_SELECTOR} h1');
                            return el ? el.textContent.trim() : document.title;
                        }}""")
                        with open(os.path.join(page_dir, "page.html"), "w", encoding="utf-8") as f:
                            f.write(build_reader_html(title, content_html, "en"))
                        with open(os.path.join(page_dir, "meta.json"), "w", encoding="utf-8") as f:
                            json.dump({"slug": slug, "url": url}, f, ensure_ascii=False)
                        ok += 1
                        if (ok + err) % 20 == 0:
                            print(f"  [{ok+err}/{len(todo)}] ok={ok} err={err} | {slug[:50]}", flush=True)
                    except Exception as e:
                        err += 1
                        continue
                browser.close()
        except Exception as e:
            print(f"  [BATCH {batch_start}] FATAL: {str(e)[:60]}", flush=True)
            err += len(batch)
    
    print(f"[Rescrape] done: ok={ok} err={err}", flush=True)

if __name__ == "__main__":
    main()
