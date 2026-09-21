#!/usr/bin/env python3
"""Parallel docs translator with per-slug deadline and subprocess isolation.

Uses ThreadPoolExecutor with internal deadline checks (not future.result timeout)
to ensure workers actually return and become available for new work.
"""

import sys, os, re, time, json, argparse, hashlib, shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import escape

from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT_DIR = os.path.join(ROOT, "content", "docs")
PROGRESS_PATH = os.path.join(ROOT, "data", "translation_progress.json")
CACHE_DIR = os.path.join(ROOT, "data", "translation_cache")
MAX_WORDS_PER_CHUNK = 160
MAX_ITEMS_PER_CHUNK = 8
MAX_RETRIES = 2
SLUG_DEADLINE = 3600  # max seconds per slug (checked internally)
API_TIMEOUT = 300  # per API call
MODEL = "glm-5.3"
REASONING_BUDGET_TOKENS = 32  # medium-level reasoning for translation
NONTRANSLATABLE_TAGS = ("svg", "pre", "code", "script", "style", "textarea")

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
    return f"""Translate each "text" value in the "translations" array from English to Simplified Chinese.

{terms_str}

Rules:
1. Return only a JSON object with the same "translations" array and object order.
2. Keep every "id" unchanged.
3. Keep product names in English: Palantir, Foundry, Apollo, Gotham, AIP.
4. Keep URLs, code identifiers, and command-line text unchanged.
5. Translate naturally and maintain technical accuracy.

JSON input:
{content}"""

_client = None

def get_client():
    global _client
    if _client is not None:
        return _client
    from openai import OpenAI
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        for p in [os.path.expanduser("~/.env"), os.path.join(ROOT, ".env"), "/Users/shanfu/cc/.env", "/Users/shanfu/cc/.baoyu-skills/.env"]:
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
    _client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout=API_TIMEOUT,
        max_retries=0,
    )
    return _client

def call_api(client, content):
    prompt = build_translation_prompt(content)
    for attempt in range(MAX_RETRIES):
        try:
            stream = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                extra_body={
                    "thinking": {
                        "type": "enabled",
                        "budget_tokens": REASONING_BUDGET_TOKENS,
                    }
                },
                timeout=API_TIMEOUT,
                stream=True,
            )
            pieces = []
            for event in stream:
                if event.choices and event.choices[0].delta and event.choices[0].delta.content:
                    pieces.append(event.choices[0].delta.content)
            return "".join(pieces)
        except Exception as e:
            s = str(e)
            if "429" in s or "rate" in s.lower():
                time.sleep(3 * (attempt + 1))
            elif attempt < MAX_RETRIES - 1:
                time.sleep(1)
            else:
                print(f"API error ({MODEL}): {str(e)[:160]}", flush=True)
                return None
    return None

def extract_article_content(html):
    m = re.search(r'<article>(.*?)</article>', html, re.DOTALL | re.I)
    return m.group(1).strip() if m else ""

def extract_text_nodes(content):
    """Return the parsed article and its visible, translatable text nodes."""
    soup = BeautifulSoup(content, "html.parser")
    entries = []
    for node in soup.find_all(string=True):
        if node.find_parent(NONTRANSLATABLE_TAGS):
            continue
        raw = str(node)
        match = re.match(r"^(\s*)(.*?)(\s*)$", raw, re.DOTALL)
        if not match or not match.group(2):
            continue
        entries.append({
            "node": node,
            "id": len(entries),
            "prefix": match.group(1),
            "suffix": match.group(3),
            "text": match.group(2),
        })
    return soup, entries

def chunk_text_entries(entries):
    chunks, current, words = [], [], 0
    for entry in entries:
        payload = {"id": entry["id"], "text": entry["text"]}
        word_count = len(entry["text"].split())
        if (
            words + word_count > MAX_WORDS_PER_CHUNK
            or len(current) >= MAX_ITEMS_PER_CHUNK
        ) and current:
            chunks.append(current)
            current, words = [payload], word_count
        else:
            current.append(payload)
            words += word_count
    if current:
        chunks.append(current)
    return chunks

def parse_translation_response(raw):
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        raise RuntimeError("translation API did not return JSON")
    data = json.loads(text[start:end + 1])
    if isinstance(data, dict) and isinstance(data.get("translations"), list):
        data = data["translations"]
    if not isinstance(data, list):
        raise RuntimeError("translation API returned invalid JSON")
    translations = {}
    for item in data:
        if not isinstance(item, dict) or "id" not in item or "text" not in item:
            raise RuntimeError("translation API omitted a text node")
        translations[str(item["id"])] = str(item["text"])
    return translations

def load_translation_cache(cache_path, source_hash, expected_ids):
    if not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version") != 1 or data.get("source_sha256") != source_hash:
            return {}
        cached = data.get("translations")
        if not isinstance(cached, dict):
            return {}
        return {
            str(key): str(value)
            for key, value in cached.items()
            if str(key) in expected_ids and str(value).strip()
        }
    except Exception:
        return {}

def save_translation_cache(cache_path, source_hash, translations):
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    data = {
        "version": 1,
        "source_sha256": source_hash,
        "translations": translations,
    }
    tmp = cache_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, cache_path)

def translate_article_content(content, client, deadline_started, cache_path=None):
    soup, entries = extract_text_nodes(content)
    if not entries:
        return None

    expected_ids = {str(entry["id"]) for entry in entries}
    source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    translations = (
        load_translation_cache(cache_path, source_hash, expected_ids)
        if cache_path else {}
    )

    chunks = chunk_text_entries(entries)
    failed_chunks = 0
    for chunk in chunks:
        if time.time() - deadline_started > SLUG_DEADLINE:
            break

        missing = [item for item in chunk if str(item["id"]) not in translations]
        if not missing:
            continue

        try:
            raw = call_api(client, json.dumps({"translations": missing}, ensure_ascii=False))
            if not raw or not raw.strip():
                raise RuntimeError("translation API returned an empty result")
            translations.update(parse_translation_response(raw))
            if cache_path:
                save_translation_cache(cache_path, source_hash, translations)
        except Exception as e:
            failed_chunks += 1
            print(
                f"Chunk failed: {len(missing)} items: {str(e)[:100]}",
                flush=True,
            )

    if set(translations) != expected_ids:
        missing_count = len(expected_ids - set(translations))
        raise RuntimeError(
            f"{missing_count} text nodes untranslated after {failed_chunks} failed chunks"
        )

    for entry in entries:
        replacement = entry["prefix"] + translations[str(entry["id"])] + entry["suffix"]
        entry["node"].replace_with(replacement)
    return str(soup)

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

def write_progress(total, completed, errors, remaining):
    data = {
        "total": total,
        "processed": completed + errors,
        "completed": completed,
        "errors": errors,
        "remaining": remaining,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    tmp = PROGRESS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PROGRESS_PATH)

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

        cache_path = os.path.join(CACHE_DIR, slug + ".json")
        translated = translate_article_content(content, client, t0, cache_path)
        if not translated:
            return slug, False, "no translation"

        translated_soup = BeautifulSoup(translated, "html.parser")
        translated_h1 = translated_soup.find("h1")
        title = translated_h1.get_text(" ", strip=True) if translated_h1 else slug
        with open(zh_path, "w", encoding="utf-8") as f:
            f.write(build_reader_html(escape(title), translated, "zh"))
        elapsed = time.time() - t0
        return slug, True, f"{elapsed:.0f}s"
    except Exception as e:
        return slug, False, str(e)[:60]

def copy_duplicate_translations():
    """Reuse translations for pages whose source HTML is byte-identical."""
    groups = {}
    for slug in os.listdir(CONTENT_DIR):
        page_dir = os.path.join(CONTENT_DIR, slug)
        en_path = os.path.join(page_dir, "page.html")
        zh_path = os.path.join(page_dir, "page_zh.html")
        if not os.path.isfile(en_path):
            continue
        with open(en_path, "rb") as f:
            source_hash = hashlib.sha256(f.read()).hexdigest()
        groups.setdefault(source_hash, []).append((slug, en_path, zh_path))

    copied = 0
    for pages in groups.values():
        completed = [
            zh_path for _, _, zh_path in pages
            if os.path.exists(zh_path) and os.path.getsize(zh_path) > 200
        ]
        if not completed:
            continue
        source_zh = completed[0]
        for slug, _, zh_path in pages:
            if zh_path == source_zh:
                continue
            if not (os.path.exists(zh_path) and os.path.getsize(zh_path) > 200):
                shutil.copyfile(source_zh, zh_path)
                copied += 1
                print(f"Reused translation: {slug}", flush=True)
    return copied

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

    copy_duplicate_translations()

    slugs = [
        d for d in os.listdir(CONTENT_DIR)
        if os.path.isfile(os.path.join(CONTENT_DIR, d, "page.html"))
    ]
    slugs.sort(key=lambda d: os.path.getsize(os.path.join(CONTENT_DIR, d, "page.html")))
    todo = []
    for slug in slugs:
        en_path = os.path.join(CONTENT_DIR, slug, "page.html")
        zh_path = os.path.join(CONTENT_DIR, slug, "page_zh.html")
        if os.path.exists(en_path) and not (os.path.exists(zh_path) and os.path.getsize(zh_path) > 200):
            todo.append(slug)
    print(f"[Translate] todo={len(todo)} workers={args.workers}", flush=True)
    write_progress(len(todo), 0, 0, len(todo))
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
            write_progress(len(todo), ok, err, len(todo) - total)
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
