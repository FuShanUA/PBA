#!/usr/bin/env python3
"""Parallel docs translator with per-slug deadline and subprocess isolation.

Uses ThreadPoolExecutor with internal deadline checks (not future.result timeout)
to ensure workers actually return and become available for new work.
"""

import sys, os, re, time, json, argparse, hashlib, shutil, threading, subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import escape, unescape

from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT_DIR = os.path.join(ROOT, "content", "docs")
PROGRESS_PATH = os.path.join(ROOT, "data", "translation_progress.json")
NODE_EVENTS_PATH = os.path.join(ROOT, "data", "translation_node_events.jsonl")
REQUEST_EVENTS_PATH = os.path.join(ROOT, "data", "translation_request_events.jsonl")
API_WORKER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "translate_api_worker.py")
CACHE_DIR = os.path.join(ROOT, "data", "translation_cache")
TEXT_CACHE_PATH = os.path.join(ROOT, "data", "translation_text_cache.json")
NODE_EVENT_LOCK = threading.Lock()
REQUEST_EVENT_LOCK = threading.Lock()
REQUEST_SEQ = 0
REQUEST_SEQ_LOCK = threading.Lock()
CACHE_LOCK = threading.Lock()
TEXT_CACHE_LOCK = threading.Lock()
NODE_TOTAL = 0
MAX_WORDS_PER_CHUNK = 600
MAX_ITEMS_PER_CHUNK = 64
MAX_CHARS_PER_CHUNK = 8000
MAX_RETRIES = 2
SLUG_DEADLINE = 7200  # max seconds per slug (checked internally)
API_TIMEOUT = 240  # per API call; two attempts stay below supervisor stall window
API_HEARTBEAT_SECONDS = 30
MODEL = "glm-5.3"
REASONING_EFFORT = "low"
NONTRANSLATABLE_TAGS = ("svg", "pre", "code", "script", "style", "textarea")
ARTICLE_FALLBACK_TO_BODY = False
ARTICLE_FORCE_BODY = False
REMOVE_FORM_SECTIONS = False
BOILERPLATE_SELECTORS = (
    "script,style,noscript,template,header,footer,nav,aside,"
    "next-route-announcer,#onetrust-consent-sdk,#onetrust-pc-sdk,"
    "[data-nosnippet='true'],[data-nosnippet=\"true\"]"
)
TYPE_SIGNATURE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*<.*>$")
CODE_ARRAY = re.compile(r"^\s*\[.*\]\s*$", re.DOTALL)
TRUNCATED_NUMERIC_ARRAY = re.compile(
    r"^\[[0-9eE\s,.+-]*(?:\.\.\.)?\]?$"
)
WKT_GEOMETRY = re.compile(
    r"^(?:POINT|LINESTRING|POLYGON|MULTIPOINT|MULTILINESTRING|MULTIPOLYGON|GEOMETRYCOLLECTION)\s*\(",
    re.IGNORECASE,
)
TYPE_UNION = re.compile(
    r"^(?:[A-Za-z][A-Za-z0-9_]*(?:<[^>]*>?)?|<[^>|]+>)(?:\s*\|\s*(?:[A-Za-z][A-Za-z0-9_]*(?:<[^>]*>?)?|<[^>|]+>))+\s*(?:,.*)?$"
)
MARKDOWN_TABLE_FRAGMENT = re.compile(
    r"^\|\s*[^|\n]+\s*\|\s*\n\|\s*[-: ]+\s*\|\s*\n\|\s*\{\s*$"
)
FIXTURE_SENTENCE = re.compile(
    r"^(?:hello world\. the quick brown fox jumps over the fence\.|hello world! how are you\? have a nice day\.|this is a test\. another test\? yes, another test!)$",
    re.IGNORECASE,
)
CONSTANT_SLASH_LIST = re.compile(
    r"^[A-Z][A-Z0-9_]*(?:\s*/\s*[A-Z][A-Z0-9_]*)+$"
)
REPEATED_TOKEN_SEQUENCE = re.compile(
    r"^(\S+)(?:\s+\1)+(?:\s*\.\.\.)?$",
    re.IGNORECASE,
)
NUMERIC_VALUE = re.compile(r"^\s*[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?\s*$")
COMMAND_LINE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(?:\s+\S+)*\s+-{1,2}[A-Za-z][\w-]*")
BREADCRUMB_PATH = re.compile(r"^(?:[^>\n]+ > )+[^>\n]+$")
DOTTED_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")
UNDERSCORE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*_[a-z0-9_]*$")
UPPER_CONSTANT = re.compile(r"^[A-Z][A-Z0-9_-]{0,7}$")
PUNCTUATION_ONLY = re.compile(r"^[^\w\s]+$")
CODE_FRAGMENT = re.compile(r"(?:->|::|\{\"|\"\}|^[a-zA-Z_]\w*\(|^[^\w\s]{1,3}$)")
SHORT_COLON_VALUE = re.compile(r"^:\s*[\w\s,{}\[\]]{0,12}$")
BLOCK_TAGS = (
    "p", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "td", "th", "caption", "figcaption",
    "summary", "dt", "dd",
)


def should_skip_text(text):
    """Leave code signatures, arrays, and numeric values untouched."""
    return bool(
        TYPE_SIGNATURE.match(text)
        or CODE_ARRAY.match(text)
        or TRUNCATED_NUMERIC_ARRAY.match(text.strip())
        or WKT_GEOMETRY.match(text.strip())
        or TYPE_UNION.match(text.strip())
        or MARKDOWN_TABLE_FRAGMENT.match(text.strip())
        or FIXTURE_SENTENCE.match(text.strip())
        or CONSTANT_SLASH_LIST.match(text.strip())
        or REPEATED_TOKEN_SEQUENCE.match(text.strip())
        or NUMERIC_VALUE.match(text)
        or COMMAND_LINE.match(text)
        or BREADCRUMB_PATH.match(text)
        or DOTTED_IDENTIFIER.match(text)
        or UNDERSCORE_IDENTIFIER.match(text)
        or UPPER_CONSTANT.match(text)
        or PUNCTUATION_ONLY.match(text)
        or CODE_FRAGMENT.match(text)
        or SHORT_COLON_VALUE.match(text)
        or (len(text) <= 2 and text.strip().isascii())
    )

def should_skip_node(node, text):
    if should_skip_text(text):
        return True
    if not text or any(char.isspace() for char in text):
        return False
    if not text.isascii() or not text.islower():
        return False
    parent = node.parent
    return parent is not None and parent.name in {"th", "td", "li"}

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

LOCAL_TRANSLATIONS = {
    ".": "。",
    ":": "：",
    "(": "（",
    ")": "）",
    ",": "，",
    "Example": "示例",
    "Example:": "示例：",
    "See details": "查看详情",
    "Output": "输出",
    "Output:": "输出：",
    "Output type:": "输出类型：",
    "Outputs:": "输出：",
    "Input:": "输入：",
    "Inputs:": "输入：",
    "Expression:": "表达式：",
    "Expressions:": "表达式：",
    "Expression categories:": "表达式类别：",
    "Expression categories": "表达式类别",
    "Transform categories": "转换类别",
    "Argument values:": "参数值：",
    "Arguments": "参数",
    "Parameters": "参数",
    "Signature:": "签名：",
    "Description:": "描述：",
    "Description": "描述",
    "Type variable bounds:": "类型变量约束：",
    "Supported": "支持",
    "Not supported": "不支持",
    "Supported in: Batch": "支持环境：Batch",
    "Supported in: Streaming": "支持环境：Streaming",
    "Supported in: Batch, Streaming": "支持环境：Batch、Streaming",
    "Supported in: Batch, Faster": "支持环境：Batch、Faster",
    "Supported in: Batch, Faster, Streaming": "支持环境：Batch、Faster、Streaming",
    "For example:": "例如：",
    "Given input table:": "给定输入表：",
    "Left dataset:": "左侧数据集：",
    "Right dataset:": "右侧数据集：",
    "Left:": "左侧：",
    "Right:": "右侧：",
    "Join key:": "连接键：",
    "Value:": "值：",
    "Angle unit:": "角度单位：",
    "Output mode:": "输出模式：",
    "Projected coordinate system:": "投影坐标系：",
    "Condition for columns to select on the left:": "左侧选择列的条件：",
    "Condition for columns to select on the right:": "右侧选择列的条件：",
    "Prefix for columns from right:": "右侧列前缀：",
    "Dataset:": "数据集：",
    "Latest changes": "最新变更",
    "Other Changes": "其他变更",
    "Other changes": "其他变更",
    "Improvement": "改进",
    "Fix": "修复",
    "Function": "函数",
    "Returns": "返回",
    "Usage": "用法",
    "Overview": "概述",
    "Actions": "操作",
    "Find and use data": "查找和使用数据",
    "Indexed datasets": "索引数据集",
    "String": "字符串",
    "Boolean": "布尔",
    "Numeric": "数值",
    "Double": "双精度浮点数",
    "Integer": "整数",
    "Long": "长整数",
    "Array": "数组",
    "Map": "映射",
    "Struct": "结构体",
    "Binary": "二进制",
    "Geospatial": "地理空间",
    "Media": "媒体",
    "Datetime": "日期时间",
    "Date": "日期",
    "Timestamp": "时间戳",
    "Aggregate": "聚合",
    "and": "和",
    "or": "或",
    "in": "在",
}

def build_translation_prompt(content):
    terms_str = "\n".join(f"  {en} -> {zh}" for en, zh in TERM_PAIRS.items())
    try:
        item_count = len(json.loads(content).get("translations", []))
    except Exception:
        item_count = "unknown"
    return f"""Translate each "text" value in the "translations" array from English to Simplified Chinese.

{terms_str}

Rules:
1. Return only a JSON object with the same "translations" array and object order.
2. Keep every "id" unchanged.
3. Keep product names in English: Palantir, Foundry, Apollo, Gotham, AIP.
4. Keep URLs, code identifiers, and command-line text unchanged.
5. Translate naturally and maintain technical accuracy.
6. Return all {item_count} items exactly once. Do not omit, merge, summarize, or truncate any item.

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


def append_request_event(status, slug, request_id, **fields):
    event = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "status": status,
        "slug": slug,
        "request_id": request_id,
    }
    event.update(fields)
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    with REQUEST_EVENT_LOCK:
        with open(REQUEST_EVENTS_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    detail = " ".join(f"{key}={value}" for key, value in fields.items())
    print(f"[Request] {status} {slug or '-'} {detail}", flush=True)


def communicate_with_api_worker(proc, content, slug, request_id, attempt):
    try:
        proc.stdin.write(content)
        proc.stdin.close()
    except Exception:
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        except Exception:
            pass

    started = time.monotonic()
    while True:
        try:
            stdout, stderr = proc.communicate(timeout=API_HEARTBEAT_SECONDS)
            return stdout, stderr, None
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - started
            append_request_event(
                "waiting",
                slug,
                request_id,
                attempt=attempt + 1,
                elapsed=round(elapsed, 1),
                phase="waiting for API worker",
            )
            if elapsed >= API_TIMEOUT:
                proc.kill()
                try:
                    stdout, stderr = proc.communicate(timeout=5)
                except Exception:
                    stdout, stderr = "", ""
                append_request_event(
                    "timeout",
                    slug,
                    request_id,
                    attempt=attempt + 1,
                    elapsed=round(elapsed, 1),
                    error=f"no completed response after {API_TIMEOUT}s",
                )
                return stdout, stderr, "timeout"


def call_api(client, content, slug=None, items=None, phase="initial"):
    global REQUEST_SEQ
    with REQUEST_SEQ_LOCK:
        REQUEST_SEQ += 1
        request_id = REQUEST_SEQ
    prompt = build_translation_prompt(content)
    item_count = len(items) if items is not None else 0
    word_count = sum(len(str(item.get("text", "")).split()) for item in items) if items is not None else 0
    append_request_event(
        "start",
        slug,
        request_id,
        phase=phase,
        chars=len(content),
        items=item_count,
        words=word_count,
    )
    for attempt in range(MAX_RETRIES):
        attempt_started = time.monotonic()
        proc = subprocess.Popen(
            [sys.executable, API_WORKER_PATH],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr, timeout_error = communicate_with_api_worker(
                proc, content, slug, request_id, attempt
            )
            if timeout_error:
                s = timeout_error
            elif proc.returncode != 0:
                s = stderr.strip() or f"API worker exited with code {proc.returncode}"
            else:
                try:
                    result = json.loads(stdout.strip())["result"]
                    append_request_event(
                        "success",
                        slug,
                        request_id,
                        attempt=attempt + 1,
                        elapsed=round(time.monotonic() - attempt_started, 1),
                        output_chars=len(result),
                    )
                    return result
                except Exception as e:
                    s = f"invalid API worker output: {str(e)[:120]}"
        except Exception as e:
            s = str(e)
            try:
                proc.kill()
            except Exception:
                pass
        finally:
            if proc.poll() is None:
                proc.kill()
            try:
                proc.wait(timeout=2)
            except Exception:
                pass

        append_request_event(
            "retry" if attempt < MAX_RETRIES - 1 else "error",
            slug,
            request_id,
            attempt=attempt + 1,
            elapsed=round(time.monotonic() - attempt_started, 1),
            error=str(s)[:160],
        )
        if "429" in s or "rate" in s.lower():
            time.sleep(3 * (attempt + 1))
        elif attempt < MAX_RETRIES - 1:
            time.sleep(1)
        else:
            print(f"API error ({MODEL}): {str(s)[:160]}", flush=True)
            return None
    return None


def _remove_boilerplate(soup):
    for node in soup.select(BOILERPLATE_SELECTORS):
        node.decompose()


def remove_form_sections(soup):
    """Drop conversion form sections before translating website prose."""
    for node in soup.select("section[id$='-form']"):
        node.decompose()
    for form in list(soup.find_all("form")):
        section = form.find_parent("section")
        section_id = section.get("id", "") if section else ""
        section_classes = " ".join(section.get("class", [])) if section else ""
        if section and (
            section_id.endswith("-form")
            or "formWrapper" in section_classes
            or "marketoForm" in section_classes
        ):
            section.decompose()
        else:
            form.decompose()


def _translatable_text_length(node):
    return len(
        " ".join(
            str(text)
            for text in node.find_all(string=True)
            if not text.find_parent(NONTRANSLATABLE_TAGS)
            and not should_skip_text(" ".join(str(text).split()))
        ).strip()
    )


def extract_article_content(html, fallback_to_body=None):
    soup = BeautifulSoup(html, "html.parser")
    use_fallback = ARTICLE_FALLBACK_TO_BODY if fallback_to_body is None else fallback_to_body
    if ARTICLE_FORCE_BODY:
        body = soup.find("body")
        if body:
            _remove_boilerplate(body)
            if REMOVE_FORM_SECTIONS:
                remove_form_sections(body)
            return "".join(str(child) for child in body.children)
        return ""
    article = soup.find("article")
    if article:
        if not use_fallback or _translatable_text_length(article) >= 100:
            return str(article)

    body = soup.find("body")
    if body and use_fallback:
        _remove_boilerplate(body)
        return "".join(str(child) for child in body.children)
    return ""

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
        if should_skip_node(node, match.group(2)):
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
    """Batch whole paragraphs first, then pack many paragraphs per request."""
    groups = []
    group_by_parent = {}
    for entry in entries:
        parent = entry["node"].find_parent(BLOCK_TAGS) or entry["node"].parent
        key = id(parent)
        if key not in group_by_parent:
            group_by_parent[key] = []
            groups.append(group_by_parent[key])
        group_by_parent[key].append(entry)

    chunks = []
    current = []
    words = 0
    chars = 0

    def flush():
        nonlocal current, words, chars
        if current:
            chunks.append(current)
        current = []
        words = 0
        chars = 0

    def append_entry(entry):
        nonlocal words, chars
        payload = {"id": entry["id"], "text": entry["text"]}
        word_count = len(entry["text"].split())
        char_count = len(entry["text"])
        if current and (
            len(current) >= MAX_ITEMS_PER_CHUNK
            or words + word_count > MAX_WORDS_PER_CHUNK
            or chars + char_count > MAX_CHARS_PER_CHUNK
        ):
            flush()
        current.append(payload)
        words += word_count
        chars += char_count

    for group in groups:
        group_words = sum(len(entry["text"].split()) for entry in group)
        group_chars = sum(len(entry["text"]) for entry in group)
        if current and (
            len(current) + len(group) > MAX_ITEMS_PER_CHUNK
            or words + group_words > MAX_WORDS_PER_CHUNK
            or chars + group_chars > MAX_CHARS_PER_CHUNK
        ):
            flush()

        if (
            len(group) > MAX_ITEMS_PER_CHUNK
            or group_words > MAX_WORDS_PER_CHUNK
            or group_chars > MAX_CHARS_PER_CHUNK
        ):
            for entry in group:
                append_entry(entry)
        else:
            for entry in group:
                payload = {"id": entry["id"], "text": entry["text"]}
                current.append(payload)
                words += len(entry["text"].split())
                chars += len(entry["text"])

    flush()
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
        # A response can be truncated after some valid items. Keep those items;
        # the caller repairs only the missing IDs instead of discarding the batch.
        if not isinstance(item, dict) or "id" not in item or "text" not in item:
            continue
        text = str(item["text"])
        if text.strip():
            translations[str(item["id"])] = text
    if not translations:
        raise RuntimeError("translation API returned no usable text nodes")
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

def load_text_cache():
    if not os.path.exists(TEXT_CACHE_PATH):
        return {}
    try:
        with open(TEXT_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return {
            str(source): str(translation)
            for source, translation in data.items()
            if source and str(translation).strip()
        }
    except Exception:
        return {}

def save_text_cache(cache):
    os.makedirs(os.path.dirname(TEXT_CACHE_PATH), exist_ok=True)
    tmp = TEXT_CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, TEXT_CACHE_PATH)

def record_text_translations(items, translations):
    with TEXT_CACHE_LOCK:
        cache = load_text_cache()
        changed = False
        for item in items:
            source = str(item.get("text", ""))
            translated = translations.get(str(item.get("id")))
            if source and translated and cache.get(source) != translated:
                cache[source] = translated
                changed = True
        if changed:
            save_text_cache(cache)


def translate_document_title(client, title, slug):
    """Translate the source <title> for pages without an h1."""
    if not title:
        return None
    cached = load_text_cache().get(title)
    if cached:
        return cached
    items = [{"id": "title", "text": title}]
    raw = call_api(
        client,
        json.dumps({"translations": items}, ensure_ascii=False),
        slug,
        items,
        "title",
    )
    if not raw:
        return title
    try:
        translations = parse_translation_response(raw)
    except Exception:
        return title
    translated = translations.get("title")
    if not translated:
        return title
    record_text_translations(items, translations)
    return translated


def translate_chunk_with_fallback(
    client,
    items,
    translations,
    cache_path,
    source_hash,
    slug,
    allow_split=True,
):
    """Translate a large batch, repair missing IDs once, then split at most once."""
    if not items:
        return True

    def request_and_apply(batch, phase):
        requested_ids = {str(item["id"]) for item in batch}
        raw = call_api(
            client,
            json.dumps({"translations": batch}, ensure_ascii=False),
            slug,
            batch,
            phase,
        )
        if not raw or not raw.strip():
            return
        try:
            returned = parse_translation_response(raw)
            valid = {
                str(key): str(value)
                for key, value in returned.items()
                if str(key) in requested_ids and str(value).strip()
            }
            if not valid:
                return
            with CACHE_LOCK:
                translations.update(valid)
                if cache_path:
                    save_translation_cache(cache_path, source_hash, translations)
            for item in batch:
                item_id = str(item["id"])
                if item_id in valid:
                    append_node_event(
                        slug,
                        item["id"],
                        item["text"],
                        valid[item_id],
                    )
        except Exception:
            return

    request_and_apply(items, "initial")

    missing = [item for item in items if str(item["id"]) not in translations]
    if not missing:
        return True

    request_and_apply(missing, "repair")
    missing = [item for item in items if str(item["id"]) not in translations]
    if not missing:
        return True

    if len(items) == 1:
        print(
            f"Chunk failed: 1 item: no valid translation returned",
            flush=True,
        )
        return False

    if not allow_split:
        print(
            f"Chunk failed: {len(missing)} items still missing after repair",
            flush=True,
        )
        return False

    # One bounded split. The recursive calls cannot split again, so a bad
    # response cannot degenerate into dozens of one-item requests.
    midpoint = len(missing) // 2
    left = missing[:midpoint]
    right = missing[midpoint:]
    return (
        translate_chunk_with_fallback(
            client, left, translations, cache_path, source_hash, slug,
            allow_split=False,
        )
        and translate_chunk_with_fallback(
            client, right, translations, cache_path, source_hash, slug,
            allow_split=False,
        )
    )

def translate_article_content(content, client, deadline_started, slug, cache_path=None):
    soup, entries = extract_text_nodes(content)
    if not entries:
        return None

    expected_ids = {str(entry["id"]) for entry in entries}
    source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    translations = (
        load_translation_cache(cache_path, source_hash, expected_ids)
        if cache_path else {}
    )
    for entry in entries:
        local_translation = LOCAL_TRANSLATIONS.get(entry["text"])
        if local_translation is not None:
            translations.setdefault(str(entry["id"]), local_translation)

    for entry in entries:
        entry_id = str(entry["id"])
        if entry_id in translations:
            append_node_event(
                slug,
                entry["id"],
                entry["text"],
                translations[entry_id],
            )

    missing_entries = [
        entry for entry in entries
        if str(entry["id"]) not in translations
    ]
    chunks = chunk_text_entries(missing_entries)
    failed_chunks = 0
    for chunk in chunks:
        if time.time() - deadline_started > SLUG_DEADLINE:
            break

        missing = [item for item in chunk if str(item["id"]) not in translations]
        if not missing:
            continue

        if not translate_chunk_with_fallback(
            client,
            missing,
            translations,
            cache_path,
            source_hash,
            slug,
        ):
            failed_chunks += 1

    if set(translations) != expected_ids:
        missing_count = len(expected_ids - set(translations))
        raise RuntimeError(
            f"{missing_count} text nodes untranslated after {failed_chunks} failed chunks"
        )

    unchanged_source_nodes = 0
    for entry in entries:
        translated_text = translations[str(entry["id"])]
        if (
            len(entry["text"].split()) >= 8
            and translated_text == entry["text"]
            and not should_skip_text(entry["text"])
        ):
            unchanged_source_nodes += 1
        replacement = entry["prefix"] + translated_text + entry["suffix"]
        entry["node"].replace_with(replacement)
    if unchanged_source_nodes >= 2:
        raise RuntimeError(
            f"{unchanged_source_nodes} source text nodes were returned unchanged"
        )
    return str(soup)

def prepare_file_state(source_path, zh_path, cache_path, slug):
    with open(source_path, "r", encoding="utf-8") as f:
        html = f.read()
    content = extract_article_content(html)
    if not content or len(content) < 50:
        return None

    source_title = ""
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.I)
    if title_match:
        source_title = " ".join(unescape(title_match.group(1)).split())

    soup, entries = extract_text_nodes(content)
    if not entries:
        return None

    expected_ids = {str(entry["id"]) for entry in entries}
    source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    translations = load_translation_cache(cache_path, source_hash, expected_ids)
    text_cache = load_text_cache()

    for entry in entries:
        local_translation = LOCAL_TRANSLATIONS.get(entry["text"])
        if local_translation is not None:
            translations.setdefault(str(entry["id"]), local_translation)
        cached_translation = text_cache.get(entry["text"])
        if cached_translation is not None:
            translations.setdefault(str(entry["id"]), cached_translation)

    for entry in entries:
        entry_id = str(entry["id"])
        if entry_id in translations:
            append_node_event(
                slug,
                entry["id"],
                entry["text"],
                translations[entry_id],
            )

    missing_entries = [
        entry for entry in entries
        if str(entry["id"]) not in translations
    ]
    representatives = []
    duplicate_ids_by_text = {}
    seen_texts = set()
    for entry in missing_entries:
        text = entry["text"]
        if text in seen_texts:
            duplicate_ids_by_text.setdefault(text, []).append(entry["id"])
        else:
            seen_texts.add(text)
            representatives.append(entry)
    chunks = chunk_text_entries(representatives)

    return {
        "slug": slug,
        "html": html,
        "source_title": source_title,
        "soup": soup,
        "entries": entries,
        "expected_ids": expected_ids,
        "source_hash": source_hash,
        "cache_path": cache_path,
        "zh_path": zh_path,
        "translations": translations,
        "chunks": chunks,
        "duplicate_ids_by_text": duplicate_ids_by_text,
    }


def prepare_page_state(slug):
    page_dir = os.path.join(CONTENT_DIR, slug)
    return prepare_file_state(
        os.path.join(page_dir, "page.html"),
        os.path.join(page_dir, "page_zh.html"),
        os.path.join(CACHE_DIR, slug + ".json"),
        slug,
    )


def finalize_page_state(page_state):
    translations = page_state["translations"]
    expected_ids = page_state["expected_ids"]
    if set(translations) != expected_ids:
        missing_count = len(expected_ids - set(translations))
        raise RuntimeError(f"{missing_count} text nodes untranslated")

    unchanged_source_nodes = 0
    for entry in page_state["entries"]:
        translated_text = translations[str(entry["id"])]
        if (
            len(entry["text"].split()) >= 8
            and translated_text == entry["text"]
            and not should_skip_text(entry["text"])
        ):
            unchanged_source_nodes += 1
        replacement = entry["prefix"] + translated_text + entry["suffix"]
        entry["node"].replace_with(replacement)
    if unchanged_source_nodes >= 2:
        raise RuntimeError(
            f"{unchanged_source_nodes} source text nodes were returned unchanged"
        )

    translated_soup = BeautifulSoup(str(page_state["soup"]), "html.parser")
    translated_h1 = translated_soup.find("h1")
    title = (
        translated_h1.get_text(" ", strip=True)
        if translated_h1
        else (
            page_state.get("translated_title")
            or page_state.get("source_title")
            or page_state["slug"]
        )
    )
    with open(page_state["zh_path"], "w", encoding="utf-8") as f:
        f.write(build_reader_html(escape(title), str(page_state["soup"]), "zh"))
    return title


def finish_file_state(page_state, client):
    for chunk in page_state["chunks"]:
        if not run_chunk_job(page_state, chunk, client):
            raise RuntimeError(f"translation chunk failed for {page_state['slug']}")
    if page_state["soup"].find("h1") is None and page_state.get("source_title"):
        page_state["translated_title"] = translate_document_title(
            client,
            page_state["source_title"],
            page_state["slug"],
        )
    return finalize_page_state(page_state)


def translate_file(source_path, zh_path, cache_path, slug):
    state = prepare_file_state(source_path, zh_path, cache_path, slug)
    if state is None:
        return None
    client = get_client()
    return finish_file_state(state, client)

def run_chunk_job(page_state, items, client):
    success = translate_chunk_with_fallback(
        client,
        items,
        page_state["translations"],
        page_state["cache_path"],
        page_state["source_hash"],
        page_state["slug"],
    )
    if not success:
        return False

    translations = page_state["translations"]
    for item in items:
        item_id = str(item["id"])
        translated = translations.get(item_id)
        if not translated:
            continue
        for duplicate_id in page_state["duplicate_ids_by_text"].get(item["text"], []):
            duplicate_id = str(duplicate_id)
            if duplicate_id in translations:
                continue
            translations[duplicate_id] = translated
            append_node_event(
                page_state["slug"],
                int(duplicate_id),
                item["text"],
                translated,
            )
        record_text_translations([item], {item_id: translated})

    with CACHE_LOCK:
        save_translation_cache(
            page_state["cache_path"],
            page_state["source_hash"],
            translations,
        )
    return True

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
    if NODE_TOTAL:
        data["node_total"] = NODE_TOTAL
    tmp = PROGRESS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PROGRESS_PATH)

def reset_node_events():
    os.makedirs(os.path.dirname(NODE_EVENTS_PATH), exist_ok=True)
    with NODE_EVENT_LOCK:
        with open(NODE_EVENTS_PATH, "w", encoding="utf-8"):
            pass

def reset_request_events():
    os.makedirs(os.path.dirname(REQUEST_EVENTS_PATH), exist_ok=True)
    with REQUEST_EVENT_LOCK:
        with open(REQUEST_EVENTS_PATH, "w", encoding="utf-8"):
            pass

def append_node_event(slug, item_id, source, translation):
    event = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "slug": slug,
        "id": item_id,
        "source": source,
        "translation": translation,
    }
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    with NODE_EVENT_LOCK:
        with open(NODE_EVENTS_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")

def count_nodes(slugs):
    total = 0
    for slug in slugs:
        en_path = os.path.join(CONTENT_DIR, slug, "page.html")
        with open(en_path, "r", encoding="utf-8") as f:
            html = f.read()
        content = extract_article_content(html)
        if not content:
            continue
        _, entries = extract_text_nodes(content)
        total += len(entries)
    return total

def translate_one_slug(slug, client):
    t0 = time.time()
    try:
        state = prepare_page_state(slug)
        if state is None:
            return slug, False, "no content"
        finish_file_state(state, client)
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
    parser.add_argument("--workers", type=int, default=3)
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

    global NODE_TOTAL
    reset_node_events()
    reset_request_events()

    page_states = []
    for slug in todo:
        state = prepare_page_state(slug)
        if state is not None:
            page_states.append(state)

    NODE_TOTAL = sum(len(state["entries"]) for state in page_states)
    jobs = [
        (state, chunk)
        for state in page_states
        for chunk in state["chunks"]
    ]

    for state in page_states:
        append_request_event(
            "cache",
            state["slug"],
            0,
            nodes=len(state["entries"]),
            cached=len(state["translations"]),
            requests=len(state["chunks"]),
        )

    print(
        f"[Translate] todo={len(todo)} workers={args.workers} "
        f"requests={len(jobs)} nodes={NODE_TOTAL}",
        flush=True,
    )
    write_progress(len(jobs), 0, 0, len(jobs))
    if not page_states:
        print("Nothing to translate.", flush=True)
        return

    ok = err = 0
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(run_chunk_job, state, chunk, client): (state, chunk)
            for state, chunk in jobs
        }
        for future in as_completed(futures):
            state, chunk = futures[future]
            try:
                success = future.result()
                info = ""
            except Exception as e:
                success = False
                info = str(e)[:40]
            if success:
                ok += 1
            else:
                err += 1
            total = ok + err
            write_progress(len(jobs), ok, err, len(jobs) - total)
            if total % 10 == 0 or total == len(jobs):
                elapsed = time.time() - start_time
                rate = total / elapsed if elapsed > 0 else 0
                remaining = len(jobs) - total
                eta = remaining / rate if rate > 0 else 0
                print(
                    f"  [{total}/{len(jobs)}] ok={ok} err={err} | "
                    f"{rate:.1f}req/s ETA={eta:.0f}s | "
                    f"{state['slug'][:35]} {info or ''}",
                    flush=True,
                )

    completed_pages = 0
    failed_pages = 0
    for state in page_states:
        try:
            finalize_page_state(state)
            completed_pages += 1
        except Exception as e:
            failed_pages += 1
            print(f"  PAGE FAIL: {state['slug']} {str(e)[:80]}", flush=True)

    print(
        f"[Translate] done: requests ok={ok} err={err}; "
        f"pages ok={completed_pages} err={failed_pages}",
        flush=True,
    )

if __name__ == "__main__":
    main()
