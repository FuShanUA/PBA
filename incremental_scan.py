#!/usr/bin/env python3
"""Incremental scan: check all sources for new content, download, translate, update index.

Usage:
  python3 incremental_scan.py              # scan all sources
  python3 incremental_scan.py --source blog    # scan only blog
  python3 incremental_scan.py --source website # scan only website
  python3 incremental_scan.py --source docs    # scan only docs
  python3 incremental_scan.py --dry-run    # report new content without downloading
  python3 incremental_scan.py --push       # auto git add, commit, push after update
"""

import json, re, os, sys, time, hashlib, urllib.request, argparse, subprocess
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))

def log(msg):
    print(f'[{datetime.now().strftime("%H:%M:%S")}] {msg}', flush=True)

# === BLOG SCANNER ===

def scan_blog(dry_run=False):
    """Check blog.palantir.com for new articles via Medium RSS feed."""
    log('--- Scanning Blog (Medium RSS) ---')
    blog_json_path = os.path.join(ROOT, 'data', 'sources', 'blog.json')
    with open(blog_json_path) as f:
        blog_data = json.load(f)
    existing_slugs = {a['s'] for a in blog_data['articles']}

    # Fetch RSS feed
    rss_url = 'https://blog.palantir.com/feed'
    try:
        req = urllib.request.Request(rss_url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            rss = resp.read().decode('utf-8')
    except Exception as e:
        log(f'  Failed to fetch RSS: {e}')
        return []

    # Parse RSS items
    items = re.findall(r'<item>(.*?)</item>', rss, re.DOTALL)
    new_articles = []
    for item in items:
        link_m = re.search(r'<link>(.*?)</link>', item)
        title_m = re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>|<title>(.*?)</title>', item)
        date_m = re.search(r'<pubDate>(.*?)</pubDate>', item)
        if not link_m:
            continue
        url = link_m.group(1).strip()
        from urllib.parse import urlparse as _up
        path = _up(url).path
        slug = path.rstrip("/").split("/")[-1]
        if not slug or slug in existing_slugs:
            continue
        if title_m:
            title = title_m.group(1) or title_m.group(2) or ''
        date = ''
        if date_m:
            try:
                dt = datetime.strptime(date_m.group(1).strip(), '%a, %d %b %Y %H:%M:%S %Z')
                date = dt.strftime('%Y-%m-%d')
            except:
                pass
        new_articles.append({
            's': slug, 'u': url, 't': title, 'd': date,
            'source': 'blog'
        })
        log(f'  NEW: {slug} ({date})')

    if not new_articles:
        log('  No new blog articles found.')
    elif dry_run:
        log(f'  Found {len(new_articles)} new articles (dry run, not downloading)')
    else:
        log(f'  Found {len(new_articles)} new articles. Downloading...')
        download_blog_articles(new_articles, blog_data)
        with open(blog_json_path, 'w', encoding='utf-8') as f:
            json.dump(blog_data, f, ensure_ascii=False, indent=2)

    return new_articles


def download_blog_articles(new_articles, blog_data):
    """Download new blog article HTML and extract data."""
    for a in new_articles:
        slug = a['s']
        url = a['u']
        article_dir = os.path.join(ROOT, 'articles', slug)
        os.makedirs(article_dir, exist_ok=True)
        html_path = os.path.join(article_dir, 'reader.html')
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode('utf-8')
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html)
            # Extract thumbnail
            th_m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
            th = th_m.group(1) if th_m else ''
            # Extract description
            desc_m = re.search(r'<meta property="og:description" content="([^"]+)"', html)
            desc = desc_m.group(1) if desc_m else ''
            # Add to blog data
            entry = {
                't': a['t'], 'tt': a['t'], 'd': a['d'], 's': slug, 'u': url,
                'bc': [], 'sc': {}, 'th': th, 'ds': desc, 'sn': desc,
                'hp': f'articles/{slug}/reader.html'
            }
            blog_data['articles'].append(entry)
            log(f'  Downloaded: {slug}')
        except Exception as e:
            log(f'  FAILED to download {slug}: {e}')


# === WEBSITE SCANNER ===

def scan_website(dry_run=False):
    """Check palantir.com sitemap for new pages."""
    log('--- Scanning Website (sitemap) ---')
    ws_json_path = os.path.join(ROOT, 'data', 'sources', 'website.json')
    with open(ws_json_path) as f:
        ws_data = json.load(f)
    existing_slugs = {a['s'] for a in ws_data['articles']}

    # Fetch sitemap
    sitemap_url = 'https://www.palantir.com/sitemap.xml'
    try:
        req = urllib.request.Request(sitemap_url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            sitemap = resp.read().decode('utf-8')
    except Exception as e:
        log(f'  Failed to fetch sitemap: {e}')
        return []

    # Parse URLs from sitemap
    urls = re.findall(r'<loc>(https://www\.palantir\.com/[^<]+)</loc>', sitemap)
    # Filter out excluded prefixes
    exclude = ['/blog', '/docs', '/sitemap', '/cookie', '/terms', '/privacy-and-security',
               '/human-rights', '/modern-slavery', '/store', '/contact', '/jp', '/uk',
               '/us-public-policy', '/responsible-business', '/news-details']
    # Non-content pages to exclude
    exclude_slugs = {'500', 'pagenotfound', 'search', 'new-homepage', 'homepage',
                     'developers', 'aip-developers', 'defense-sdk', 'foundation',
                     'veterans', 'usg-recruitment', 'sovereignaios',
                     'sovereignaios-modelengine', 'protect-your-sovereignty',
                     'security-forge', 'devcon4', 'devcon5', 'offerings'}
    new_urls = []
    for url in urls:
        path = urlparse(url).path
        if any(path.startswith(ex) for ex in exclude):
            continue
        slug = path.strip('/').replace('/', '-')
        if not slug or slug in existing_slugs or slug in exclude_slugs:
            continue
        new_urls.append((slug, url))

    if not new_urls:
        log('  No new website pages found.')
    elif dry_run:
        log(f'  Found {len(new_urls)} new pages (dry run):')
        for slug, url in new_urls[:20]:
            log(f'    {slug} -> {url}')
    else:
        log(f'  Found {len(new_urls)} new pages. Use scrape_website.py to download them.')
        log('  (Website scraping requires Playwright. Run: python3 scrapers/scrape_website.py)')

    return new_urls



# === DOCS SCANNER ===

def scan_docs(dry_run=False):
    """Check palantir.com/docs sitemap for new documentation pages."""
    log('--- Scanning Docs (sitemap) ---')
    docs_json_path = os.path.join(ROOT, 'data', 'sources', 'docs.json')
    if not os.path.exists(docs_json_path):
        log('  docs.json not found, skipping docs scan')
        return []
    with open(docs_json_path) as f:
        docs_data = json.load(f)
    existing_slugs = {a['s'] for a in docs_data['articles']}

    # Fetch sitemap
    sitemap_url = 'https://www.palantir.com/docs/sitemap.xml'
    try:
        req = urllib.request.Request(sitemap_url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=60) as resp:
            sitemap = resp.read().decode('utf-8')
    except Exception as e:
        log(f'  Failed to fetch docs sitemap: {e}')
        return []

    # Parse zh URLs and convert to English
    urls = re.findall(r'<loc>(https?://[^<]+)</loc>', sitemap)
    new_pages = []
    for u in urls:
        u = u.replace('https://palantir.com', 'https://www.palantir.com')
        path = urlparse(u).path
        if '/docs/zh/' not in path:
            continue
        en_path = path.replace('/docs/zh/', '/docs/')
        en_url = f'https://www.palantir.com{en_path}'
        slug = en_path.strip('/').replace('docs/', '').replace('/', '-')
        if not slug or slug == 'docs' or slug in existing_slugs:
            continue
        new_pages.append((slug, en_url))

    if not new_pages:
        log('  No new docs pages found.')
    elif dry_run:
        log(f'  Found {len(new_pages)} new docs pages (dry run):')
        for slug, url in new_pages[:20]:
            log(f'    {slug} -> {url}')
    else:
        log(f'  Found {len(new_pages)} new docs pages. Use scrape_docs.py to download them.')
        log('  (Docs scraping requires Playwright. Run: python3 scrapers/scrape_docs.py --scrape)')

    return new_pages


# === TRANSLATION ===

def translate_new_articles():
    """Translate any new articles that don't have Chinese versions yet."""
    log('--- Checking for untranslated articles ---')
    sys.path.insert(0, '/Users/shanfu/cc/Library/Tools/common')
    sys.path.insert(0, '/Users/shanfu/cc/Library/Tools/postfdry/agents')
    try:
        from llm_utils import get_client, LLMProvider
        import translator_agent
        import markdown as md_lib
        client = get_client()
    except Exception as e:
        log(f'  Cannot load translation tools: {e}')
        return

    # Check blog articles
    blog_json = os.path.join(ROOT, 'data', 'sources', 'blog.json')
    with open(blog_json) as f:
        blog_data = json.load(f)
    for a in blog_data['articles']:
        zh_path = a.get('hp', '').replace('reader.html', 'reader_zh.html')
        if not zh_path:
            continue
        full_zh = os.path.join(ROOT, zh_path)
        if not os.path.exists(full_zh):
            en_path = a.get('hp', '').replace('reader_zh.html', 'reader.html')
            full_en = os.path.join(ROOT, en_path)
            if os.path.exists(full_en):
                log(f'  Translating blog: {a["s"]}')
                translate_article_file(full_en, full_zh, client, translator_agent, md_lib)
                # Translate title
                if a.get('tt') == a.get('t'):
                    a['tt'] = translate_title(a['t'], client)
    with open(blog_json, 'w', encoding='utf-8') as f:
        json.dump(blog_data, f, ensure_ascii=False, indent=2)

    # Check docs articles
    docs_json = os.path.join(ROOT, 'data', 'sources', 'docs.json')
    if os.path.exists(docs_json):
        with open(docs_json) as f:
            docs_data = json.load(f)
        for a in docs_data['articles']:
            zh_path = a.get('hp', '').replace('page.html', 'page_zh.html')
            if not zh_path:
                continue
            full_zh = os.path.join(ROOT, zh_path)
            if not os.path.exists(full_zh):
                en_path = a.get('hp', '').replace('page_zh.html', 'page.html')
                full_en = os.path.join(ROOT, en_path)
                if os.path.exists(full_en):
                    log(f'  Translating docs: {a["s"]}')
                    translate_article_file(full_en, full_zh, client, translator_agent, md_lib)
        with open(docs_json, 'w', encoding='utf-8') as f:
            json.dump(docs_data, f, ensure_ascii=False, indent=2)

    # Check website articles
    ws_json = os.path.join(ROOT, 'data', 'sources', 'website.json')
    with open(ws_json) as f:
        ws_data = json.load(f)
    for a in ws_data['articles']:
        if a.get('hidden'):
            continue
        zh_path = a.get('hp', '').replace('page.html', 'page_zh.html')
        if not zh_path:
            continue
        full_zh = os.path.join(ROOT, zh_path)
        if not os.path.exists(full_zh):
            en_path = a.get('hp', '').replace('page_zh.html', 'page.html')
            full_en = os.path.join(ROOT, en_path)
            if os.path.exists(full_en):
                log(f'  Translating website: {a["s"]}')
                translate_article_file(full_en, full_zh, client, translator_agent, md_lib)
                if a.get('tt') == a.get('t'):
                    a['tt'] = translate_title(a['t'], client)
    with open(ws_json, 'w', encoding='utf-8') as f:
        json.dump(ws_data, f, ensure_ascii=False, indent=2)


def translate_title(title, client):
    """Translate a single title."""
    prompt = f'''Translate the following English title to Chinese. Keep product names (Palantir, Foundry, Apollo, Gotham, AIP, ShipOS, Warp Speed, Vertex) in English. Output ONLY the Chinese translation.

Title: {title}'''
    try:
        resp = client.generate_content(
            content=prompt, model_name='glm-5.2',
            provider=LLMProvider.DASHSCOPE, fallback=False
        )
        return resp.strip().strip('"').strip('\u201c').strip('\u201d')
    except:
        return title


def translate_article_file(en_path, zh_path, client, translator_agent, md_lib):
    """Translate an HTML article file to Chinese, preserving paragraph structure."""
    with open(en_path, 'r', encoding='utf-8') as f:
        html = f.read()
    # Extract text content from HTML
    text = re.sub(r'<[^>]+>', '\n', html)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    if not text or len(text) < 50:
        return
    try:
        # Chunk if long
        words = text.split()
        if len(words) > 800:
            chunks = []
            paras = text.split('\n\n')
            current = ''
            for p in paras:
                if len(current.split()) + len(p.split()) > 800 and current:
                    chunks.append(current)
                    current = p
                else:
                    current = current + '\n\n' + p if current else p
            if current:
                chunks.append(current)
        else:
            chunks = [text]

        translated_chunks = []
        for chunk in chunks:
            prompt = translator_agent.build_translation_prompt(chunk, style='formal')
            resp = client.generate_content(
                content=prompt, model_name='glm-5.2',
                provider=LLMProvider.DASHSCOPE, fallback=False
            )
            translated_chunks.append(resp.strip())

        translated = '\n\n'.join(translated_chunks)
        # Render as HTML
        rendered = md_lib.Markdown(extensions=['extra', 'sane_lists', 'nl2br']).convert(translated)
        # Wrap in basic HTML
        zh_html = f'''<!DOCTYPE html>
<html lang="zh"><head><meta charset="UTF-8">
<style>body{{max-width:800px;margin:0 auto;padding:24px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;line-height:1.8;}}</style>
</head><body>{rendered}</body></html>'''
        with open(zh_path, 'w', encoding='utf-8') as f:
            f.write(zh_html)
        log(f'    Saved: {os.path.basename(zh_path)}')
    except Exception as e:
        log(f'    Translation failed: {e}')


# === MAIN ===

def main():
    parser = argparse.ArgumentParser(description='Incremental scan for new Palantir content')
    parser.add_argument('--source', choices=['blog', 'website', 'docs', 'all'], default='all')
    parser.add_argument('--push', action='store_true', help='Auto git add, commit, push after update')
    parser.add_argument('--dry-run', action='store_true', help='Report new content without downloading')
    parser.add_argument('--no-translate', action='store_true', help='Skip translation step')
    args = parser.parse_args()

    log(f'Starting incremental scan (source={args.source}, dry_run={args.dry_run})')

    new_blog = []
    new_website = []
    if args.source in ('blog', 'all'):
        new_blog = scan_blog(dry_run=args.dry_run)
    if args.source in ('website', 'all'):
        new_website = scan_website(dry_run=args.dry_run)
    new_docs = []
    if args.source in ('docs', 'all'):
        new_docs = scan_docs(dry_run=args.dry_run)

    total_new = len(new_blog) + len(new_website) + len(new_docs)
    if total_new > 0 and not args.dry_run and not args.no_translate:
        translate_new_articles()

    # Rebuild index
    if total_new > 0 and not args.dry_run:
        log('--- Rebuilding index ---')
        subprocess.run([sys.executable, os.path.join(ROOT, 'build.py')], cwd=ROOT)

    log(f'\nScan complete. New content: {total_new} ({len(new_blog)} blog, {len(new_website)} website, {len(new_docs)} docs)')

    if not args.dry_run and total_new > 0:
        if args.push:
            log('--- Pushing to GitHub ---')
            subprocess.run(['git', 'add', '-A'], cwd=ROOT)
            subprocess.run(['git', 'commit', '-m', f'Incremental update: {total_new} new articles ({len(new_blog)} blog, {len(new_website)} website, {len(new_docs)} docs)'], cwd=ROOT)
            result = subprocess.run(['git', 'push', 'origin', 'main'], cwd=ROOT, capture_output=True, text=True)
            if result.returncode == 0:
                log('  Pushed to GitHub successfully')
            else:
                log(f'  Push failed: {result.stderr[:100]}')
        else:
            log('To push to GitHub: git add -A && git commit -m "Add new content" && git push')
            log('Or re-run with --push to auto-push')


if __name__ == '__main__':
    main()
