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
sys.path.insert(0, ROOT)

from scrapers.translate_parallel import translate_file

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

def _translate_source_articles(source):
    """Translate missing source pages with the shared GLM pipeline."""
    source_json = os.path.join(ROOT, 'data', 'sources', f'{source}.json')
    with open(source_json, encoding='utf-8') as f:
        data = json.load(f)

    translated = 0
    changed = False
    for article in data.get('articles', []):
        if article.get('hidden'):
            continue
        source_rel = article.get('hp', '')
        if not source_rel:
            continue
        if source == 'blog':
            zh_rel = source_rel.replace('reader.html', 'reader_zh.html')
        else:
            zh_rel = source_rel.replace('page.html', 'page_zh.html')
        source_path = os.path.join(ROOT, source_rel)
        zh_path = os.path.join(ROOT, zh_rel)
        if not os.path.isfile(source_path) or (
            os.path.isfile(zh_path) and os.path.getsize(zh_path) > 200
        ):
            continue

        slug = article.get('s') or os.path.basename(os.path.dirname(source_path))
        log(f'  Translating {source}: {slug}')
        cache_path = os.path.join(
            ROOT, 'data', 'translation_cache', f'{source}-{slug}.json'
        )
        title = translate_file(source_path, zh_path, cache_path, slug)
        if title and article.get('tt', article.get('t')) == article.get('t'):
            article['tt'] = title
        translated += 1
        changed = True
        log(f'    Saved: {os.path.basename(zh_path)}')

    if changed:
        with open(source_json, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return translated


def translate_blog_articles():
    log('--- Checking for untranslated blog articles ---')
    count = _translate_source_articles('blog')
    log(f'  Blog translation complete: {count} new pages')
    return count


def translate_website_articles():
    log('--- Checking for untranslated website pages ---')
    count = _translate_source_articles('website')
    log(f'  Website translation complete: {count} new pages')
    return count


def translate_new_articles():
    """Translate new blog and website pages with the shared pipeline."""
    return {
        'blog': translate_blog_articles(),
        'website': translate_website_articles(),
    }


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
        if args.dry_run:
            new_docs = scan_docs(dry_run=True)
        else:
            updater = os.path.join(ROOT, 'tools', 'update_docs.py')
            command = [sys.executable, updater, '--workers', '3']
            if args.no_translate:
                command.append('--no-translate')
            result = subprocess.run(command, cwd=ROOT)
            if result.returncode != 0:
                log('  Docs update failed')
            else:
                try:
                    with open(os.path.join(ROOT, 'data', 'docs_update_summary.json')) as f:
                        docs_summary = json.load(f)
                    new_docs = (
                        docs_summary.get('new_slugs', [])
                        + docs_summary.get('changed_slugs', [])
                    )
                except Exception:
                    new_docs = []

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
