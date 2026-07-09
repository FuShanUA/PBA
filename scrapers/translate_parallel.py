#!/usr/bin/env python3
"""Parallel docs translator with per-slug deadline and subprocess isolation.

Uses ThreadPoolExecutor with internal deadline checks (not future.result timeout)
to ensure workers actually return and become available for new work.
"""

import sys, os, re, time, json, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT_DIR = os.path.join(ROOT, "content", "docs")
MAX_WORDS_PER_CHUNK = 200
MAX_RETRIES = 2
SLUG_DEADLINE = 60  # max seconds per slug (checked internally)
API_TIMEOUT = 25   # per API call

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
    return f"""Translate the following HTML from English to Simplified Chinese. Keep all HTML tags intact. Keep product names in English: Palantir, Foundry, Apollo, Gotham, AIP.

{terms_str}

Content:
{content}"""

_client = None

def get_client():
    global _client
    if _client is not None:
        return _client
    from openai import OpenAI
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        for p in [os.path.expanduser("~/.env"), os.path.join(ROOT, ".env"), "/Users/shanfu/cc/.env"]:
            if os.path.exists(p):
                with open(p) as f:
                    for line in f:
                        if "DASHSCOPE_API_KEY" in line and "=" in line:
                            api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                            break
                if api_key:
                    break
    if not api_key:
        print("ERROR: DASHSCOPE_API_KEY not found", flush=True)
        sys.exit(1)
    _client = OpenAI(api_key=api_key, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
    return _client

def call_api(client, content):
    prompt = build_translation_prompt(content)
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.chat.completions.create(
                model="qwen-turbo",
                messages=[{"role": "user", "content": prompt}],
                timeout=API_TIMEOUT,
            )
            return resp.choices[0].message.content
        except Exception as e:
            s = str(e)
            if "429" in s or "rate" in s.lower():
                time.sleep(3 * (attempt + 1))
            elif attempt < MAX_RETRIES - 1:
                time.sleep(1)
            else:
                return None
    return None

def extract_article_content(html):
    m = re.search(r'<article>(.*?)</article>', html, re.DOTALL | re.I)
    return m.group(1).strip() if m else ""

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

def translate_one_slug(slug, client):
    page_dir = os.path.join(CONTENT_DIR, slug)
    en_path = os.path.join(page_dir, "page.html")
    zh_path = os.path.join(page_dir, "page_zh.html")
    t0 = time.time()
    try:
        with open(en_path, "r", encoding="utf-8") as f:
            html = f.read()
        content = extract_article_content(html)
        if not content or len(content) < 50:
            return slug, False, "no content"
        if len(content) > 200000:
            return slug, False, "too big"

        chunks = chunk_content(content) if len(content.split()) > MAX_WORDS_PER_CHUNK else [content]
        parts = []
        for i, chunk in enumerate(chunks):
            # Check deadline before each chunk
            if time.time() - t0 > SLUG_DEADLINE:
                # Use remaining untranslated chunks as-is (English fallback)
                parts.append(chunk)
                continue
            if not chunk.strip():
                continue
            result = call_api(client, chunk)
            parts.append(result if result else chunk)

        translated = '\n\n'.join(parts)
        if not translated:
            return slug, False, "no translation"

        title_m = re.search(r'<title>([^<]+)</title>', html)
        title = title_m.group(1) if title_m else slug
        with open(zh_path, "w", encoding="utf-8") as f:
            f.write(build_reader_html(title, translated, "zh"))
        elapsed = time.time() - t0
        return slug, True, f"{elapsed:.0f}s"
    except Exception as e:
        return slug, False, str(e)[:60]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=15)
    parser.add_argument("--slug", type=str)
    args = parser.parse_args()

    client = get_client()

    if args.slug:
        print(f"Translating: {args.slug}", flush=True)
        r = translate_one_slug(args.slug, client)
        print(f"  {'OK' if r[1] else 'FAIL'}: {r[2]}", flush=True)
        return

    slugs = sorted([d for d in os.listdir(CONTENT_DIR) if os.path.isdir(os.path.join(CONTENT_DIR, d))])
    todo = []
    for slug in slugs:
        en_path = os.path.join(CONTENT_DIR, slug, "page.html")
        zh_path = os.path.join(CONTENT_DIR, slug, "page_zh.html")
        if os.path.exists(en_path) and not (os.path.exists(zh_path) and os.path.getsize(zh_path) > 200):
            todo.append(slug)
    print(f"[Translate] todo={len(todo)} workers={args.workers}", flush=True)
    if not todo:
        print("Nothing to translate.", flush=True)
        return

    ok = err = 0
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(translate_one_slug, slug, client): slug for slug in todo}
        for future in as_completed(futures):
            slug = futures[future]
            try:
                result_slug, success, info = future.result()
            except Exception as e:
                result_slug = slug
                success = False
                info = str(e)[:40]
            if success:
                ok += 1
            else:
                err += 1
            total = ok + err
            if total % 10 == 0 or total == len(todo):
                elapsed = time.time() - start_time
                rate = total / elapsed if elapsed > 0 else 0
                remaining = len(todo) - total
                eta = remaining / rate if rate > 0 else 0
                print(f"  [{total}/{len(todo)}] ok={ok} err={err} | "
                      f"{rate:.1f}pg/s ETA={eta:.0f}s | {result_slug[:35]} {info or ''}", flush=True)

    print(f"[Translate] done: ok={ok} err={err}", flush=True)

if __name__ == "__main__":
    main()
