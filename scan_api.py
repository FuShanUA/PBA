#!/usr/bin/env python3
"""Importable scan logic with progress callbacks for the content-update UI.

Wraps the existing incremental_scan.py and scrape_website.py flows so the
web frontend can trigger updates for individual sources (blog, website)
and receive structured progress + result data.
"""

import json, re, os, sys, time, subprocess, urllib.request, traceback
from datetime import datetime, timezone
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "scrapers"))

SOURCES = ["blog", "website", "docs"]

# Auto-filter patterns for website articles
import re as _re
LOCALE_RE = _re.compile(r"/(de|fr|es|ja|zh|ko|pt|it)/?$")
BAD_TITLE_RE = _re.compile(r"(Untitled|^500 Error|^404|Page Not Found|^Error$)", _re.I)
DOWNLOAD_RE = _re.compile(r"/download$|/-download$")
from website_taxonomy import is_non_content_path

def _should_auto_hide(article):
    """Auto-filter non-content pages and obvious broken pages."""
    url = article.get("u", "")
    title = article.get("t", "")
    if is_non_content_path(urlparse(url).path):
        return "non-content page"
    if BAD_TITLE_RE.match(title) or not title.strip():
        return "empty/error title"
    if DOWNLOAD_RE.search(url):
        return "download page"
    return None

def _find_python(require_modules=None):
    """Find a python executable that can import every required module."""
    if isinstance(require_modules, str):
        require_modules = [require_modules]
    candidates = []
    venv = os.path.join(ROOT, ".venv", "bin", "python")
    if os.path.exists(venv):
        candidates.append(venv)
    candidates.append(sys.executable)
    candidates.append("/opt/homebrew/bin/python3")
    candidates.append("python3")
    for py in candidates:
        if not require_modules:
            return py
        try:
            checks = [
                subprocess.run(
                    [py, "-c", f"import {module}"],
                    capture_output=True,
                    timeout=10,
                )
                for module in require_modules
            ]
            if all(check.returncode == 0 for check in checks):
                return py
        except Exception:
            continue
    return candidates[0] if candidates else sys.executable

def _ts():
    return datetime.now().strftime("%H:%M:%S")


def _source_file(source):
    return os.path.join(ROOT, "data", "sources", f"{source}.json")


def source_status():
    """Return current counts + last-scan for each supported source."""
    out = {}
    for src in SOURCES:
        path = _source_file(src)
        info = {"count": 0, "last_scan": ""}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
                arts = [a for a in d.get("articles", []) if not a.get("hidden")]
                info["count"] = len(arts)
                info["last_scan"] = d.get("last_scan", "")
            except Exception:
                pass
        out[src] = info
    return out



def _download_blog_article_pw(url, html_path):
    """Download a blog article using Playwright (headful) to bypass Cloudflare.
    
    Returns (html, og_image, og_description) or raises on failure.
    """
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        )
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if resp.status != 200:
                raise Exception(f"HTTP {resp.status}")
            page.wait_for_timeout(5000)
            html = page.content()
            og_image = page.evaluate('''(function(){var m=document.querySelector('meta[property=\"og:image\"]');return m?m.content:''})''')
            og_desc = page.evaluate('''(function(){var m=document.querySelector('meta[property=\"og:description\"]');return m?m.content:''})''')
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
            return html, og_image, og_desc
        finally:
            browser.close()


def scan_blog(progress=None):
    """Scan blog.palantir.com RSS for new articles, download + index them."""
    if progress is None:
        progress = lambda msg: None
    progress({"phase": "blog:fetch", "msg": f"[{_ts()}] 获取博客 RSS feed..."})
    blog_json_path = _source_file("blog")
    with open(blog_json_path, encoding="utf-8") as f:
        blog_data = json.load(f)
    existing_slugs = {a["s"] for a in blog_data["articles"]}

    rss_url = "https://blog.palantir.com/feed"
    try:
        req = urllib.request.Request(rss_url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            rss = resp.read().decode("utf-8")
    except Exception as e:
        progress({"phase": "blog:error", "msg": f"[{_ts()}] RSS 获取失败: {e}"})
        return {"new": 0, "error": str(e)}

    items = re.findall(r"<item>(.*?)</item>", rss, re.DOTALL)
    new_articles = []
    for item in items:
        link_m = re.search(r"<link>(.*?)</link>", item)
        title_m = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>|<title>(.*?)</title>", item)
        date_m = re.search(r"<pubDate>(.*?)</pubDate>", item)
        if not link_m:
            continue
        url = link_m.group(1).strip()
        path = urlparse(url).path
        slug = path.rstrip("/").split("/")[-1]
        if not slug or slug in existing_slugs:
            continue
        title = ""
        if title_m:
            title = title_m.group(1) or title_m.group(2) or ""
        date = ""
        if date_m:
            try:
                dt = datetime.strptime(date_m.group(1).strip(), "%a, %d %b %Y %H:%M:%S %Z")
                date = dt.strftime("%Y-%m-%d")
            except Exception:
                pass
        new_articles.append({"s": slug, "u": url, "t": title, "d": date, "source": "blog"})

    if not new_articles:
        progress({"phase": "blog:done", "msg": f"[{_ts()}] 博客无新文章"})
        return {"new": 0}

    progress({"phase": "blog:download", "msg": f"[{_ts()}] 发现 {len(new_articles)} 篇新博客，开始下载..."})
    for a in new_articles:
        slug = a["s"]
        url = a["u"]
        article_dir = os.path.join(ROOT, "articles", slug)
        os.makedirs(article_dir, exist_ok=True)
        html_path = os.path.join(article_dir, "reader.html")
        html = None
        th = ""
        desc = ""
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
            th_m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
            th = th_m.group(1) if th_m else ""
            desc_m = re.search(r'<meta property="og:description" content="([^"]+)"', html)
            desc = desc_m.group(1) if desc_m else ""
        except Exception as e:
            progress({"phase": "blog:download", "msg": f"[{_ts()}]   urllib 失败 ({e}), 尝试 Playwright..."})
            try:
                html, th, desc = _download_blog_article_pw(url, html_path)
            except Exception as e2:
                progress({"phase": "blog:download", "msg": f"[{_ts()}]   下载失败 {slug}: {e2}"})
                html = None
        if html:
            entry = {
                "t": a["t"], "tt": a["t"], "d": a["d"], "s": slug, "u": url,
                "bc": [], "sc": {}, "th": th, "ds": desc, "sn": desc,
                "hp": f"articles/{slug}/reader.html",
            }
            blog_data["articles"].append(entry)
            progress({"phase": "blog:download", "msg": f"[{_ts()}]   下载完成: {slug}"})

    blog_data["last_scan"] = datetime.now(timezone.utc).isoformat()
    with open(blog_json_path, "w", encoding="utf-8") as f:
        json.dump(blog_data, f, ensure_ascii=False, indent=2)
    progress({"phase": "blog:done", "msg": f"[{_ts()}] 博客更新完成，新增 {len(new_articles)} 篇"})
    return {"new": len(new_articles)}


def scan_website(progress=None):
    """Run the website scraper via subprocess, streaming its stdout as progress."""
    if progress is None:
        progress = lambda msg: None
    progress({"phase": "website:start", "msg": f"[{_ts()}] 启动官网 Playwright 爬虫..."})
    scraper_path = os.path.join(ROOT, "scrapers", "scrape_website.py")
    python = _find_python(["playwright", "bs4"])
    try:
        proc = subprocess.Popen(
            [python, scraper_path],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                progress({"phase": "website:scrape", "msg": f"[{_ts()}] {line}"})
        proc.wait()
        if proc.returncode != 0:
            progress({"phase": "website:error", "msg": f"[{_ts()}] 爬虫退出码 {proc.returncode}"})
            return {"new": 0, "error": f"exit code {proc.returncode}"}
        progress({"phase": "website:done", "msg": f"[{_ts()}] 官网更新完成"})
        _postprocess_website(progress)
        summary_path = os.path.join(ROOT, "data", "website_update_summary.json")
        summary = {"new": 0, "changed": 0, "has_updates": False}
        if os.path.exists(summary_path):
            try:
                with open(summary_path, encoding="utf-8") as f:
                    summary = json.load(f)
            except Exception:
                pass
        return {
            "new": summary.get("new", 0),
            "changed": summary.get("changed", 0),
            "has_updates": bool(summary.get("new", 0) or summary.get("changed", 0)),
        }
    except Exception as e:
        progress({"phase": "website:error", "msg": f"[{_ts()}] 爬虫启动失败: {e}"})
        return {"new": 0, "error": str(e)}


def scan_docs(progress=None, translate=True):
    """Check and fetch new or changed English documentation pages."""
    if progress is None:
        progress = lambda msg: None
    progress({"phase": "docs:start", "msg": f"[{_ts()}] 检查技术文档更新..."})
    updater = os.path.join(ROOT, "tools", "update_docs.py")
    python = _find_python(["bs4", "requests"])
    try:
        command = [python, updater, "--workers", "3"]
        if not translate:
            command.append("--no-translate")
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=86400,
        )
        for line in result.stdout.splitlines():
            if line.strip():
                progress({"phase": "docs:scan", "msg": line})
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()[-500:]
            progress({"phase": "docs:error", "msg": f"[{_ts()}] 文档更新失败: {message}"})
            return {"new": 0, "changed": 0, "error": message}
    except Exception as e:
        progress({"phase": "docs:error", "msg": f"[{_ts()}] 文档更新异常: {e}"})
        return {"new": 0, "changed": 0, "error": str(e)}

    summary_path = os.path.join(ROOT, "data", "docs_update_summary.json")
    summary = {"new": 0, "changed": 0, "has_updates": False}
    try:
        with open(summary_path, encoding="utf-8") as f:
            summary = json.load(f)
    except Exception:
        pass
    new = int(summary.get("new", 0))
    changed = int(summary.get("changed", 0))
    progress({"phase": "docs:done", "msg": f"[{_ts()}] 文档检查完成，新增 {new} 页，变更 {changed} 页"})
    return {
        "new": new,
        "changed": changed,
        "has_updates": bool(new or changed),
        "translation": summary.get("translation", {}),
    }


def _postprocess_website(progress=None):
    """After scraping, apply filters and mark new articles as pending.

    - Restore hidden/excluded state from persisted lists
    - Auto-hide locale variants, error pages, download pages
    - Mark genuinely new articles as pending (not visible until user approves)
    """
    if progress is None:
        progress = lambda msg: None
    ws_path = _source_file("website")
    with open(ws_path, encoding="utf-8") as f:
        data = json.load(f)

    excluded_slugs = set(data.get("excluded_slugs", []))
    approved_slugs = set(data.get("approved_slugs", []))
    old_slugs = _load_baseline_slugs()

    pending_count = 0
    hidden_count = 0
    for a in data["articles"]:
        slug = a.get("s", "")
        if slug in excluded_slugs:
            a["hidden"] = True
            a.pop("pending", None)
            hidden_count += 1
            continue
        reason = _should_auto_hide(a)
        if reason:
            a["hidden"] = True
            a.pop("pending", None)
            excluded_slugs.add(slug)
            hidden_count += 1
            continue
        if slug in approved_slugs or slug in old_slugs["approved"]:
            a.pop("hidden", None)
            a.pop("pending", None)
            continue
        if slug in old_slugs["hidden"]:
            a["hidden"] = True
            excluded_slugs.add(slug)
            hidden_count += 1
            continue
        if not a.get("hidden"):
            a["pending"] = True
            pending_count += 1

    data["excluded_slugs"] = sorted(excluded_slugs)
    data["approved_slugs"] = sorted(approved_slugs | old_slugs["approved"])
    data["last_scan"] = datetime.now(timezone.utc).isoformat()
    with open(ws_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    progress({"phase": "website:filter", "msg": f"[{_ts()}] 过滤完成: {pending_count} 篇待审, {hidden_count} 篇自动隐藏"})


def _load_baseline_slugs():
    """Load the curated baseline of approved/hidden slugs from git HEAD."""
    import subprocess as _sp
    try:
        r = _sp.run(["git", "show", "HEAD:data/sources/website.json"],
                     capture_output=True, text=True, timeout=10, cwd=ROOT)
        if r.returncode != 0:
            return {"approved": set(), "hidden": set()}
        old = json.loads(r.stdout)
        approved = {a["s"] for a in old.get("articles", []) if not a.get("hidden")}
        hidden = {a["s"] for a in old.get("articles", []) if a.get("hidden")}
        return {"approved": approved, "hidden": hidden}
    except Exception:
        return {"approved": set(), "hidden": set()}

def rebuild_index(progress=None):
    """Rebuild data/index.json from all source JSONs."""
    if progress is None:
        progress = lambda msg: None
    progress({"phase": "build", "msg": f"[{_ts()}] 重建索引 index.json..."})
    python = _find_python()
    try:
        result = subprocess.run(
            [python, os.path.join(ROOT, "build.py")],
            cwd=ROOT, capture_output=True, text=True, timeout=120,
        )
        for line in result.stdout.strip().splitlines():
            progress({"phase": "build", "msg": f"[{_ts()}] {line}"})
        if result.returncode != 0:
            progress({"phase": "build:error", "msg": f"[{_ts()}] 索引重建失败: {result.stderr[:200]}"})
            return False
        progress({"phase": "build:done", "msg": f"[{_ts()}] 索引重建完成"})
        return True
    except Exception as e:
        progress({"phase": "build:error", "msg": f"[{_ts()}] 索引重建异常: {e}"})
        return False


def translate_docs(progress=None):
    """Translate documentation with the shared batch GLM 5.3 pipeline."""
    if progress is None:
        progress = lambda msg: None
    python = _find_python(["bs4", "requests"])
    supervisor = os.path.join(ROOT, "tools", "translation_forever.py")
    try:
        result = subprocess.run(
            [python, supervisor, "--workers", "3", "--max-rounds", "5"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=86400,
        )
        for line in result.stdout.splitlines():
            if line.strip():
                progress({"phase": "translate:docs", "msg": line})
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()[-500:]
            progress({"phase": "translate:error", "msg": f"[{_ts()}] 文档翻译失败: {message}"})
            return False
        subprocess.run(
            [python, os.path.join(ROOT, "gen_docs_json.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        progress({"phase": "translate:done", "msg": f"[{_ts()}] 文档翻译完成"})
        return True
    except Exception as e:
        progress({"phase": "translate:error", "msg": f"[{_ts()}] 文档翻译异常: {e}"})
        return False


def translate(progress=None, sources=None):
    """Run translation for selected sources."""
    if progress is None:
        progress = lambda msg: None
    progress({"phase": "translate", "msg": f"[{_ts()}] 检查并翻译新内容..."})
    sources = sources or SOURCES
    if "docs" in sources:
        translate_docs(progress)

    if "blog" not in sources and "website" not in sources:
        return True

    inline_parts = ["import sys; sys.path.insert(0, '" + ROOT + "'); import incremental_scan as isc"]
    if "blog" in sources and "website" in sources:
        inline_parts.append("isc.translate_new_articles()")
    elif "blog" in sources:
        inline_parts.append("isc.translate_blog_articles()")
    elif "website" in sources:
        inline_parts.append("isc.translate_website_articles()")
    inline = "; ".join(inline_parts)
    python = _find_python(["bs4", "requests"])
    try:
        result = subprocess.run(
            [python, "-c", inline],
            cwd=ROOT, capture_output=True, text=True, timeout=600,
        )
        for line in result.stdout.strip().splitlines():
            progress({"phase": "translate", "msg": f"[{_ts()}] {line}"})
        if result.returncode != 0:
            progress({"phase": "translate:error", "msg": f"[{_ts()}] 翻译失败: {result.stderr[:200]}"})
            return False
        progress({"phase": "translate:done", "msg": f"[{_ts()}] 翻译完成"})
        return True
    except Exception as e:
        progress({"phase": "translate:error", "msg": f"[{_ts()}] 翻译异常: {e}"})
        return False


def review_pending(source, slugs, action):
    """Apply a review action to pending articles.

    action: "approve" -> remove pending flag, add to approved_slugs
            "exclude" -> set hidden=True, add to excluded_slugs (skip in future scans)
            "delete" -> remove article entirely from source data
    Returns {"ok": True, "affected": N} and rebuilds index.
    """
    src_path = _source_file(source)
    with open(src_path, encoding="utf-8") as f:
        data = json.load(f)
    excluded = set(data.get("excluded_slugs", []))
    approved = set(data.get("approved_slugs", []))
    slug_set = set(slugs)
    affected = 0
    new_articles = []
    for a in data["articles"]:
        slug = a.get("s", "")
        if slug not in slug_set:
            new_articles.append(a)
            continue
        if action == "approve":
            a.pop("pending", None)
            a.pop("hidden", None)
            approved.add(slug)
            new_articles.append(a)
            affected += 1
        elif action == "exclude":
            a["hidden"] = True
            a.pop("pending", None)
            excluded.add(slug)
            new_articles.append(a)
            affected += 1
        elif action == "delete":
            # Remove from articles and content dir
            content_dir = os.path.join(ROOT, "content", source, slug)
            if os.path.isdir(content_dir):
                import shutil
                shutil.rmtree(content_dir, ignore_errors=True)
            excluded.add(slug)
            affected += 1
            # Don't append — article is removed
    data["articles"] = new_articles
    data["excluded_slugs"] = sorted(excluded)
    data["approved_slugs"] = sorted(approved)
    with open(src_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # Rebuild index
    venv_python = os.path.join(ROOT, ".venv", "bin", "python")
    py = venv_python if os.path.exists(venv_python) else sys.executable
    subprocess.run([py, os.path.join(ROOT, "build.py")], cwd=ROOT, capture_output=True, text=True, timeout=120)
    return {"ok": True, "action": action, "affected": affected}


def run_update(sources, progress=None, do_translate=True):
    """Run a full update cycle for the given sources.

    sources: list of source names from SOURCES.
    progress: callback(dict) called with {"phase","msg"} updates.
    Returns final summary dict.
    """
    if progress is None:
        progress = lambda msg: None
    progress({"phase": "start", "msg": f"[{_ts()}] 开始更新: {', '.join(sources)}"})

    summary = {}
    for src in sources:
        if src == "blog":
            summary["blog"] = scan_blog(progress)
        elif src == "website":
            summary["website"] = scan_website(progress)
        elif src == "docs":
            summary["docs"] = scan_docs(progress, translate=do_translate)

    if do_translate:
        # Docs are translated inside scan_docs so the updater and translator
        # share one manifest and cannot process the same slugs twice.
        non_docs_sources = [src for src in sources if src != "docs"]
        if non_docs_sources:
            translate(progress, non_docs_sources)

    # Rebuild AFTER translate so translated titles (tt) land in index.json
    rebuild_index(progress)

    status = source_status()
    has_updates = any(
        bool(item.get("new", 0) or item.get("changed", 0))
        for item in summary.values()
    )
    complete = {
        "summary": summary,
        "status": status,
        "has_updates": has_updates,
    }
    message = "没有更新" if not has_updates else "发现内容更新"
    progress({"phase": "complete", "msg": f"[{_ts()}] 更新全部完成：{message}", **complete})
    return complete
