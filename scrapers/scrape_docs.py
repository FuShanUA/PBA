#!/usr/bin/env python3
"""Batch scraper for Palantir Documentation.
Phase 1 (--scrape):  scrape English originals -> page.html + meta.json
Phase 2 (--translate): translate page.html -> page_zh.html (multi-threaded)
Default: both phases sequentially.
Resumable: skips pages that already have the target file."""

import sys, os, re, time, json, argparse, signal
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

# --- Translation pipeline ---
POSTFDRY = "/Users/shanfu/cc/Library/Tools/postfdry"
COMMON = "/Users/shanfu/cc/Library/Tools/common"
sys.path.insert(0, COMMON)
sys.path.insert(0, os.path.join(POSTFDRY, "agents"))
from llm_utils import get_client, LLMProvider
import translator_agent

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT_DIR = os.path.join(ROOT, "content", "docs")
SITEMAP_PATH = os.path.join(ROOT, "data", "docs_sitemap.xml")
client = get_client()
MODEL = "glm-5.2"
PROVIDER = LLMProvider.DASHSCOPE
MAX_WORDS_PER_CHUNK = 800
CONTENT_SELECTOR = "div.ptcom-design__markdownDoc__1uarhel"
TRANSLATE_WORKERS = 1
TRANSLATE_TIMEOUT = 90  # seconds per GLM call

# ---------- shared helpers ----------

def parse_sitemap():
    with open(SITEMAP_PATH, "r", encoding="utf-8") as f:
        xml = f.read()
    urls = re.findall(r'<loc>(https?://[^<]+)</loc>', xml)
    entries = []
    for u in urls:
        u = u.replace("https://palantir.com", "https://www.palantir.com")
        path = urlparse(u).path
        if "/docs/zh/" not in path:
            continue
        en_path = path.replace("/docs/zh/", "/docs/")
        en_url = f"https://www.palantir.com{en_path}"
        slug = en_path.strip("/").replace("docs/", "").replace("/", "-")
        if not slug or slug == "docs":
            continue
        entries.append((slug, en_url))
    return entries

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

def chunk_content(content):
    blocks = re.split(r'(\n\s*</?(?:p|div|h[1-6]|ul|ol|li|pre|blockquote|figure|figcaption|table|tr|td|th|section)[^>]*>\s*\n?)', content)
    chunks, current, words = [], [], 0
    for block in blocks:
        if not block.strip():
            continue
        wc = len(block.split())
        if words + wc > MAX_WORDS_PER_CHUNK and current:
            chunks.append(''.join(current))
            current, words = [block], wc
        else:
            current.append(block)
            words += wc
    if current:
        chunks.append(''.join(current))
    return chunks

def extract_article_content(html):
    m = re.search(r'<article>(.*?)</article>', html, re.DOTALL | re.I)
    return m.group(1).strip() if m else ""

# ---------- Phase 1: scrape ----------

def scrape_page_safe(page, slug, url):
    """Scrape a single page. Returns 'ok'|'skip'|'error'."""
    page_dir = os.path.join(CONTENT_DIR, slug)
    os.makedirs(page_dir, exist_ok=True)
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        if not resp or resp.status != 200:
            return "error:status"
        page.wait_for_timeout(2000)
        content_html = page.evaluate(f"""() => {{
            const el = document.querySelector('{CONTENT_SELECTOR}');
            return el ? el.innerHTML : '';
        }}""")
        if not content_html or len(content_html) < 50:
            return "error:nocontent"
        title = page.evaluate(f"""() => {{
            const el = document.querySelector('{CONTENT_SELECTOR} h1');
            return el ? el.textContent.trim() : document.title;
        }}""")
        with open(os.path.join(page_dir, "page.html"), "w", encoding="utf-8") as f:
            f.write(build_reader_html(title, content_html, "en"))
        with open(os.path.join(page_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump({"slug": slug, "url": url}, f, ensure_ascii=False)
        return "ok"
    except Exception as e:
        return f"error:{str(e)[:40]}"

BATCH_SIZE = 50

def scrape_phase(entries):
    """Scrape all English pages, save page.html + meta.json. Restarts browser every BATCH_SIZE pages."""
    os.makedirs(CONTENT_DIR, exist_ok=True)
    todo = []
    done = 0
    for slug, url in entries:
        en_path = os.path.join(CONTENT_DIR, slug, "page.html")
        if os.path.exists(en_path) and os.path.getsize(en_path) > 200:
            done += 1
        else:
            todo.append((slug, url))
    print(f"[Scrape] total={len(entries)} done={done} todo={len(todo)}", flush=True)
    if not todo:
        return

    ok = err = 0
    total = len(todo)
    for batch_start in range(0, total, BATCH_SIZE):
        batch = todo[batch_start:batch_start + BATCH_SIZE]
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                for slug, url in batch:
                    result = scrape_page_safe(page, slug, url)
                    if result == "ok":
                        ok += 1
                    else:
                        err += 1
                    processed = ok + err
                    if processed % 10 == 0 or ok <= 3 or result.startswith("error"):
                        print(f"  [{done+processed}/{len(entries)}] {result}: {slug[:45]}", flush=True)
                browser.close()
        except Exception as e:
            print(f"  [BATCH {batch_start}] FATAL: {str(e)[:60]}", flush=True)
            err += len(batch)
    print(f"[Scrape] done: ok={ok} err={err}", flush=True)

# ---------- Phase 2: translate ----------

def glm_call(prompt):
    """Call GLM directly. Returns result or None."""
    try:
        return client.generate_content(content=prompt, model_name=MODEL, provider=PROVIDER, fallback=False)
    except Exception:
        return None

def translate_one(slug):
    """Translate a single page. Returns (slug, 'ok'|'skip'|'error:...')."""
    page_dir = os.path.join(CONTENT_DIR, slug)
    en_path = os.path.join(page_dir, "page.html")
    zh_path = os.path.join(page_dir, "page_zh.html")

    if os.path.exists(zh_path) and os.path.getsize(zh_path) > 200:
        return slug, "skip"

    if not os.path.exists(en_path):
        return slug, "error:nosrc"

    try:
        with open(en_path, "r", encoding="utf-8") as f:
            html = f.read()
        content = extract_article_content(html)
        if not content or len(content) < 50:
            return slug, "error:short"
        # Skip very large pages for now (process later)
        if len(content) > 50000:
            return slug, "error:toobig"

        # Translate
        chunks = chunk_content(content) if len(content.split()) > MAX_WORDS_PER_CHUNK else [content]
        parts = []
        for chunk in chunks:
            if not chunk.strip():
                continue
            prompt = translator_agent.build_translation_prompt(chunk, style="formal")
            result = glm_call(prompt)
            time.sleep(2)
            parts.append(result if result else chunk)

        translated = '\n\n'.join(parts)
        if not translated:
            return slug, "error:empty"

        # Extract title from EN html
        title_m = re.search(r'<title>([^<]+)</title>', html)
        title = title_m.group(1) if title_m else slug

        with open(zh_path, "w", encoding="utf-8") as f:
            f.write(build_reader_html(title, translated, "zh"))
        return slug, "ok"
    except Exception as e:
        return slug, f"error:{str(e)[:50]}"

def translate_phase(entries):
    """Translate all scraped pages using thread pool."""
    slugs = [slug for slug, _ in entries]
    # Filter to pages that have page.html but no page_zh.html
    todo = []
    done = 0
    for slug in slugs:
        en_path = os.path.join(CONTENT_DIR, slug, "page.html")
        zh_path = os.path.join(CONTENT_DIR, slug, "page_zh.html")
        if not os.path.exists(en_path):
            continue
        if os.path.exists(zh_path) and os.path.getsize(zh_path) > 200:
            done += 1
        else:
            todo.append(slug)
    print(f"[Translate] total={len(slugs)} already_done={done} todo={len(todo)} workers={TRANSLATE_WORKERS}", flush=True)
    if not todo:
        return

    ok = err = 0
    for slug in todo:
        try:
            slug_r, status = translate_one(slug)
        except Exception as e:
            slug_r, status = slug, f"error:{str(e)[:40]}"
        if status == "ok":
            ok += 1
        elif status == "skip":
            continue
        else:
            err += 1
        total_done = ok + err
        if total_done % 10 == 0 or ok <= 3 or status.startswith("error"):
            print(f"  [Translate {total_done}/{len(todo)}] ok={ok} err={err} | {slug_r[:40]} -> {status}", flush=True)

    print(f"[Translate] done: ok={ok} err={err}", flush=True)

# ---------- main ----------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scrape", action="store_true", help="Only scrape English pages")
    parser.add_argument("--translate", action="store_true", help="Only translate existing pages")
    args = parser.parse_args()

    entries = parse_sitemap()
    print(f"Total docs pages: {len(entries)}", flush=True)

    if args.scrape and not args.translate:
        scrape_phase(entries)
    elif args.translate and not args.scrape:
        translate_phase(entries)
    else:
        scrape_phase(entries)
        translate_phase(entries)

if __name__ == "__main__":
    main()
