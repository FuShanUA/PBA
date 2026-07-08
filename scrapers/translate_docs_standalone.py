#!/usr/bin/env python3
"""Standalone docs translator - no postfdry dependency.
Uses DashScope (百炼) GLM-5.2 API directly via OpenAI-compatible endpoint.

Usage:
  python3 scrapers/translate_docs_standalone.py           # translate all untranslated
  python3 scrapers/translate_docs_standalone.py --scrape  # scrape English pages first
  python3 scrapers/translate_docs_standalone.py --full    # scrape + translate

Requirements:
  pip install openai playwright
  playwright install chromium
  export DASHSCOPE_API_KEY=your_key_here
"""

import sys, os, re, time, json, argparse
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT_DIR = os.path.join(ROOT, "content", "docs")
MAX_WORDS_PER_CHUNK = 400
CONTENT_SELECTOR = "div.ptcom-design__markdownDoc__1uarhel"

# --- Term pairs (from postfdry config/terms.yml) ---
TERM_PAIRS = {
    "Foundry": "Foundry", "Apollo": "Apollo", "Gotham": "Gotham", "AIP": "AIP",
    "Ontology": "本体论", "ontology": "本体论", "Pipeline": "管道", "pipeline": "管道",
    "Transform": "转换", "transform": "转换", "Workshop": "Workshop", "workshop": "Workshop",
    "Contour": "Contour", "Quiver": "Quiver", "Slate": "Slate", "Code Workbook": "Code Workbook",
    "Code Repositories": "代码仓库", "Code Workspaces": "代码工作区",
    "Data Integration": "数据集成", "Model Integration": "模型集成",
    "Object": "对象", "object": "对象", "Dataset": "数据集", "dataset": "数据集",
    "Tenant": "租户", "tenant": "租户", "Marking": "标记", "marking": "标记",
    "Permission": "权限", "permission": "权限", "Role": "角色", "role": "角色",
    "Function": "函数", "function": "函数", "Action": "操作", "action": "操作",
    "Backing": "支撑", "backing": "支撑", "Link": "关联", "link": "关联",
    "Property": "属性", "property": "属性", "Interface": "接口", "interface": "接口",
}

def build_translation_prompt(content):
    terms_str = "\n".join(f"  {en} -> {zh}" for en, zh in TERM_PAIRS.items())
    return f"""You are a professional technical translator. Translate the following HTML content from English to Simplified Chinese.

Rules:
1. Keep all HTML tags intact - only translate text content
2. Keep product names in English: Palantir, Foundry, Apollo, Gotham, AIP, ShipOS, Warp Speed, Vertex
3. Use these term translations:
{terms_str}
4. Keep code blocks, URLs, and file paths unchanged
5. Translate naturally and fluently, maintaining technical accuracy

Content to translate:
{content}"""

# --- GLM API (direct, no postfdry) ---
def get_glm_client():
    from openai import OpenAI
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        # Try reading from .env
        env_paths = [
            os.path.expanduser("~/.env"),
            os.path.join(ROOT, ".env"),
            "/Users/shanfu/cc/Library/Tools/postfdry/.env",
            "/Users/shanfu/cc/Library/Tools/common/.env",
        ]
        for p in env_paths:
            if os.path.exists(p):
                with open(p) as f:
                    for line in f:
                        if "DASHSCOPE_API_KEY" in line and "=" in line:
                            api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                            break
                if api_key:
                    break
    if not api_key:
        print("ERROR: DASHSCOPE_API_KEY not found. Set it as env var or in .env", flush=True)
        sys.exit(1)
    return OpenAI(api_key=api_key, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")

def glm_translate(client, content):
    """Call GLM-5.2 to translate content. Returns translated string or None."""
    prompt = build_translation_prompt(content)
    try:
        resp = client.chat.completions.create(
            model="glm-5.2",
            messages=[{"role": "user", "content": prompt}],
            timeout=90,
        )
        return resp.choices[0].message.content
    except Exception as e:
        print(f"  GLM error: {str(e)[:60]}", flush=True)
        return None

# --- Content extraction ---
def extract_article_content(html):
    m = re.search(r'<article>(.*?)</article>', html, re.DOTALL | re.I)
    return m.group(1).strip() if m else ""

def extract_h1(html):
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
    return re.sub(r'<[^>]+>', '', m.group(1)).strip() if m else None

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

# --- Navigation tree extraction ---
def extract_nav_tree():
    """Extract complete docs navigation tree from palantir.com/docs."""
    from playwright.sync_api import sync_playwright

    def extract_urls(items, depth=0):
        urls = []
        if not isinstance(items, list):
            return urls
        for item in items:
            link = item.get('link', {})
            url = link.get('url', '')
            text = link.get('text', '')
            if url:
                urls.append({'url': url, 'title': text, 'depth': depth})
            for key in ['items', 'subItems', 'children', 'nestedItems']:
                if item.get(key):
                    urls.extend(extract_urls(item[key], depth + 1))
        return urls

    foundry_sections = [
        '/docs/foundry/getting-started/overview/',
        '/docs/foundry/data-integration/overview/',
        '/docs/foundry/model-integration/overview/',
        '/docs/foundry/ontology/overview/',
        '/docs/foundry/dev-toolchain/overview/',
        '/docs/foundry/app-building/overview/',
        '/docs/foundry/observability/overview/',
        '/docs/foundry/analytics/overview/',
        '/docs/foundry/devops/overview/',
        '/docs/foundry/security/overview/',
        '/docs/foundry/administration/overview/',
        '/docs/foundry/architecture-center/overview/',
        '/docs/foundry/aip/overview/',
        '/docs/foundry/announcements/',
        '/docs/foundry/api-reference/',
        '/docs/foundry/developers/',
    ]
    apollo_sections = [
        '/docs/apollo/core/introduction/',
        '/docs/apollo/apollo-getting-started/getting-started-with-apollo/',
        '/docs/apollo/apollo-references/apollo-references/',
    ]
    gotham_sections = ['/docs/gotham/security/overview/']
    all_sections = [('foundry', u) for u in foundry_sections] + \
                   [('apollo', u) for u in apollo_sections] + \
                   [('gotham', u) for u in gotham_sections]

    all_urls = set()
    all_pages = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True, viewport={"width": 1280, "height": 900})
        page = context.new_page()
        for product, section_url in all_sections:
            full_url = f"https://www.palantir.com{section_url}"
            try:
                page.goto(full_url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)
            except:
                continue
            result = page.evaluate("""() => {
                var el = document.getElementById('__NEXT_DATA__');
                if (!el) return null;
                var d = JSON.parse(el.textContent);
                var pp = d.props && d.props.pageProps ? d.props.pageProps : {};
                var snp = pp.sidebarNavProps;
                if (!snp) return null;
                return snp;
            }""")
            if not result:
                continue
            urls = extract_urls(result.get('items', []))
            for u in urls:
                path = u['url']
                if path not in all_urls:
                    all_urls.add(path)
                    full_path = '/docs' + path if not path.startswith('/docs') else path
                    all_pages.append({
                        'product': product,
                        'path': full_path,
                        'title': u['title'],
                        'url': f"https://www.palantir.com{full_path}"
                    })
            print(f"{product}/{section_url.split('/')[-2]}: {len(urls)} links", flush=True)
        browser.close()

    print(f"\nTotal unique pages: {len(all_pages)}", flush=True)
    # Save
    nav_path = os.path.join(ROOT, "data", "docs_nav_tree.json")
    with open(nav_path, "w") as f:
        json.dump(all_pages, f, ensure_ascii=False, indent=2)
    print(f"Saved to {nav_path}")
    return all_pages

# --- Scrape phase ---
def scrape_phase(pages):
    from playwright.sync_api import sync_playwright
    os.makedirs(CONTENT_DIR, exist_ok=True)
    todo = []
    for p in pages:
        slug = p['path'].replace('/docs/', '').rstrip('/').replace('/', '-')
        en_path = os.path.join(CONTENT_DIR, slug, "page.html")
        if os.path.exists(en_path) and os.path.getsize(en_path) > 200:
            continue
        todo.append((slug, p['url']))
    print(f"[Scrape] todo={len(todo)}", flush=True)
    if not todo:
        return

    BATCH_SIZE = 50
    ok = err = 0
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
                            err += 1; continue
                        page.wait_for_timeout(2000)
                        content_html = page.evaluate(f"""() => {{
                            const el = document.querySelector('{CONTENT_SELECTOR}');
                            return el ? el.innerHTML : '';
                        }}""")
                        if not content_html or len(content_html) < 50:
                            err += 1; continue
                        title = page.evaluate(f"""() => {{
                            const el = document.querySelector('{CONTENT_SELECTOR} h1');
                            return el ? el.textContent.trim() : document.title;
                        }}""")
                        with open(os.path.join(page_dir, "page.html"), "w", encoding="utf-8") as f:
                            f.write(build_reader_html(title, content_html, "en"))
                        with open(os.path.join(page_dir, "meta.json"), "w", encoding="utf-8") as f:
                            json.dump({"slug": slug, "url": url}, f, ensure_ascii=False)
                        ok += 1
                        if ok % 20 == 0:
                            print(f"  [{ok+err}/{len(todo)}] scraped: {slug[:50]}", flush=True)
                    except Exception:
                        err += 1; continue
                browser.close()
        except Exception as e:
            print(f"  [BATCH {batch_start}] FATAL: {str(e)[:60]}", flush=True)
            err += len(batch)
    print(f"[Scrape] done: ok={ok} err={err}", flush=True)

# --- Translate phase ---
def translate_phase():
    client = get_glm_client()
    slugs = sorted([d for d in os.listdir(CONTENT_DIR) if os.path.isdir(os.path.join(CONTENT_DIR, d))])
    todo = []
    for slug in slugs:
        en_path = os.path.join(CONTENT_DIR, slug, "page.html")
        zh_path = os.path.join(CONTENT_DIR, slug, "page_zh.html")
        if os.path.exists(en_path) and not (os.path.exists(zh_path) and os.path.getsize(zh_path) > 200):
            todo.append(slug)
    print(f"[Translate] todo={len(todo)}", flush=True)
    if not todo:
        return

    ok = err = 0
    for slug in todo:
        page_dir = os.path.join(CONTENT_DIR, slug)
        en_path = os.path.join(page_dir, "page.html")
        zh_path = os.path.join(page_dir, "page_zh.html")
        try:
            with open(en_path, "r", encoding="utf-8") as f:
                html = f.read()
            content = extract_article_content(html)
            if not content or len(content) < 50:
                err += 1; continue
            if len(content) > 200000:
                err += 1; print(f"  skip toobig: {slug[:40]}", flush=True); continue

            chunks = chunk_content(content) if len(content.split()) > MAX_WORDS_PER_CHUNK else [content]
            parts = []
            for chunk in chunks:
                if not chunk.strip():
                    continue
                result = glm_translate(client, chunk)
                parts.append(result if result else chunk)
                time.sleep(2)

            translated = '\n\n'.join(parts)
            if not translated:
                err += 1; continue

            title_m = re.search(r'<title>([^<]+)</title>', html)
            title = title_m.group(1) if title_m else slug
            with open(zh_path, "w", encoding="utf-8") as f:
                f.write(build_reader_html(title, translated, "zh"))
            ok += 1
            if ok % 10 == 0:
                print(f"  [{ok+err}/{len(todo)}] ok={ok} err={err} | {slug[:40]}", flush=True)
        except Exception as e:
            err += 1
            print(f"  ERROR: {slug[:40]} {str(e)[:40]}", flush=True)

    print(f"[Translate] done: ok={ok} err={err}", flush=True)

# --- Main ---
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scrape", action="store_true")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()

    # Get page list
    nav_path = os.path.join(ROOT, "data", "docs_nav_tree.json")
    pages = None
    if os.path.exists(nav_path):
        with open(nav_path) as f:
            pages = json.load(f)
        print(f"Loaded {len(pages)} pages from {nav_path}", flush=True)
    else:
        print("Navigation tree not found. Extracting from palantir.com...", flush=True)
        pages = extract_nav_tree()

    if args.scrape:
        scrape_phase(pages)
    elif args.full:
        scrape_phase(pages)
        translate_phase()
    else:
        translate_phase()

if __name__ == "__main__":
    main()
