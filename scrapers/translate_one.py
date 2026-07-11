#!/usr/bin/env python3
"""Translate large docs pages. Code blocks are excluded from translation."""
import sys, os, re, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT_DIR = os.path.join(ROOT, "content", "docs")
MAX_WORDS = 200
DEADLINE = 1200  # 5 min per page, should be enough for 20-25 chunks
API_TIMEOUT = 30

TERM_PAIRS = {
    "Foundry": "Foundry", "Apollo": "Apollo", "Gotham": "Gotham", "AIP": "AIP",
    "Ontology": "本体论", "ontology": "本体论", "Pipeline": "管道", "pipeline": "管道",
    "Transform": "转换", "transform": "转换", "Workshop": "Workshop", "workshop": "Workshop",
    "Code Repositories": "代码仓库", "Code Workspaces": "代码工作区",
    "Data Integration": "数据集成", "Model Integration": "模型集成",
    "Object": "对象", "object": "对象", "Dataset": "数据集", "dataset": "数据集",
    "Tenant": "租户", "tenant": "租户", "Marking": "标记", "marking": "标记",
    "Permission": "权限", "permission": "权限", "Role": "角色", "role": "角色",
    "Function": "函数", "function": "函数", "Action": "操作", "action": "操作",
    "Property": "属性", "property": "属性", "Interface": "接口", "interface": "接口",
    "Backing": "支撑", "backing": "支撑", "Link": "关联", "link": "关联",
}

def get_client():
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
    return OpenAI(api_key=api_key, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")

def translate_chunk(client, content):
    terms = "\n".join(f"  {en} -> {zh}" for en, zh in TERM_PAIRS.items())
    prompt = f"""Translate the following HTML text from English to Simplified Chinese.

Rules:
1. Do NOT translate code blocks, code snippets, or anything inside <pre>, <code> tags
2. For field names and type names, keep the English and add Chinese in parentheses after, e.g. Float（浮点）, GeoPoint（地理点位）, String（字符串）
3. Do NOT translate proper nouns: TypeScript, JavaScript, Python, Palantir, Foundry, Apollo, Gotham, AIP, ShipOS, Warp Speed, Vertex
4. Keep all HTML tags intact - only translate visible text
5. Term translations:
{terms}

Content to translate:
{content}"""
    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model="qwen-turbo",
                messages=[{"role": "user", "content": prompt}],
                timeout=API_TIMEOUT,
            )
            return resp.choices[0].message.content
        except Exception:
            if attempt == 0:
                time.sleep(3)
            else:
                return None
    return None

def extract_content(html):
    m = re.search(r'<article>(.*?)</article>', html, re.DOTALL | re.I)
    return m.group(1).strip() if m else ""

def extract_and_replace_code(content):
    """Replace <pre> and <code> blocks with placeholders. Returns (content_with_placeholders, code_map)."""
    code_map = {}
    counter = [0]
    
    def replace_match(m):
        key = f"___CODE_BLOCK_{counter[0]}___"
        code_map[key] = m.group(0)
        counter[0] += 1
        return key
    
    # Replace <pre> blocks first (they may contain <code>)
    result = re.sub(r'<pre[^>]*>.*?</pre>', replace_match, content, flags=re.DOTALL | re.I)
    # Then replace standalone <code> blocks
    result = re.sub(r'<code[^>]*>.*?</code>', replace_match, result, flags=re.DOTALL | re.I)
    
    return result, code_map

def restore_code(content, code_map):
    """Restore code blocks from placeholders."""
    for key, code in code_map.items():
        content = content.replace(key, code)
    return content

def chunk_it(content):
    """Split text content into chunks of MAX_WORDS words."""
    # Split by HTML tags
    blocks = re.split(r'(<[^>]+>)', content)
    if len(blocks) < 5:
        # Fallback: split by words
        words = content.split()
        return [' '.join(words[i:i+MAX_WORDS]) for i in range(0, len(words), MAX_WORDS)]
    
    chunks, current, words = [], [], 0
    for block in blocks:
        if not block.strip():
            continue
        wc = len(block.split())
        # If block is too large, force split by words
        if wc > MAX_WORDS * 2:
            if current:
                chunks.append(''.join(current))
                current, words = [], 0
            w = block.split()
            for i in range(0, len(w), MAX_WORDS):
                chunks.append(' '.join(w[i:i+MAX_WORDS]))
            continue
        if words + wc > MAX_WORDS and current:
            chunks.append(''.join(current))
            current, words = [block], wc
        else:
            current.append(block)
            words += wc
    if current:
        chunks.append(''.join(current))
    return chunks

def build_html(title, content, lang="zh"):
    la = "zh-CN" if lang == "zh" else "en"
    return f'''<!DOCTYPE html>
<html lang="{la}">
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
{content}
</article>
</body>
</html>'''

def main():
    slug = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read().strip()
    if not slug:
        return
    page_dir = os.path.join(CONTENT_DIR, slug)
    en_path = os.path.join(page_dir, "page.html")
    zh_path = os.path.join(page_dir, "page_zh.html")
    t0 = time.time()
    try:
        with open(en_path, "r", encoding="utf-8") as f:
            html = f.read()
        content = extract_content(html)
        if not content or len(content) < 50:
            print(f"EMPTY {slug}", flush=True)
            return
        
        # Extract code blocks, replace with placeholders
        text_content, code_map = extract_and_replace_code(content)
        text_words = len(text_content.split())
        
        client = get_client()
        chunks = chunk_it(text_content)
        total_chunks = len(chunks)
        print(f"START {slug}: {total_chunks} chunks, {text_words} text words, {len(code_map)} code blocks", flush=True)
        
        parts = []
        done = 0
        for chunk in chunks:
            if time.time() - t0 > DEADLINE:
                parts.append(chunk)
                continue
            if not chunk.strip():
                continue
            result = translate_chunk(client, chunk)
            parts.append(result if result else chunk)
            done += 1
            if done % 10 == 0:
                elapsed = time.time() - t0
                print(f"  {slug}: {done}/{total_chunks} chunks, {elapsed:.0f}s", flush=True)
        
        translated_text = '\n\n'.join(parts)
        # Restore code blocks
        translated = restore_code(translated_text, code_map)
        
        title_m = re.search(r'<title>([^<]+)</title>', html)
        title = title_m.group(1) if title_m else slug
        with open(zh_path, "w", encoding="utf-8") as f:
            f.write(build_html(title, translated))
        elapsed = time.time() - t0
        print(f"OK {slug} {done}/{total_chunks} chunks, {len(code_map)} code blocks restored, {elapsed:.0f}s", flush=True)
    except Exception as e:
        print(f"ERR {slug} {str(e)[:60]}", flush=True)

if __name__ == "__main__":
    main()
