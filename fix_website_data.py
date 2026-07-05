#!/usr/bin/env python3
"""Fix website article data: dates, categories, thumbnails, srcset, titles."""

import json, re, os, sys, hashlib, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
WS_PATH = os.path.join(ROOT, "data", "sources", "website.json")
IMG_DIR = os.path.join(ROOT, "content", "website", "images")

MONTHS_MAP = {
    'january': '01', 'february': '02', 'march': '03', 'april': '04',
    'may': '05', 'june': '06', 'july': '07', 'august': '08',
    'september': '09', 'october': '10', 'november': '11', 'december': '12',
}

LETTER_SLUGS_OTHER = {
    'q1-2024-letter-en', 'q1-2025-letter-en', 'q2-2024-letter-en',
    'q2-2025-letter-en', 'q3-2023-letter-en', 'q3-2024-letter-en',
    'q3-2025-letter-en', 'q4-2024-letter-en', 'q4-2025-letter-en',
}


def extract_date_from_html(html):
    m = re.search(
        r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})',
        html, re.IGNORECASE)
    if m:
        mo = MONTHS_MAP[m.group(1).lower()]
        day = m.group(2).zfill(2)
        return f'{m.group(3)}-{mo}-{day}'
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', html)
    if m:
        return m.group(0)
    return ''


def extract_date_from_slug(slug):
    s = slug.lower()
    m = re.search(r'q([1-4])[-_](\d{4})', s)
    if m:
        qend = {'1': '03-31', '2': '06-30', '3': '09-30', '4': '12-31'}[m.group(1)]
        return f'{m.group(2)}-{qend}'
    m = re.search(r'(\d{4})[-_]?annual[-_]?letter', s)
    if m:
        return f'{m.group(1)}-12-31'
    m = re.search(r'(\d{1,2})-(\d{1,2})-(\d{4})', s)
    if m:
        return f'{m.group(3)}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}'
    m = re.search(
        r'(january|february|march|april|may|june|july|august|september|october|november|december)-(\d{1,2})-(\d{4})',
        s)
    if m:
        return f'{m.group(3)}-{MONTHS_MAP[m.group(1)]}-{m.group(2).zfill(2)}'
    m = re.match(r'^(\d{4})-', s)
    if m:
        return f'{m.group(1)}-01-01'
    return ''


def download_image(url):
    try:
        os.makedirs(IMG_DIR, exist_ok=True)
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        ext = '.jpg'
        m = re.search(r'\.(jpg|jpeg|png|gif|webp|svg)', url, re.IGNORECASE)
        if m:
            ext = '.' + m.group(1).lower()
            if ext == '.jpeg':
                ext = '.jpg'
        filename = url_hash + ext
        filepath = os.path.join(IMG_DIR, filename)
        if os.path.exists(filepath):
            return f'content/website/images/{filename}'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        with open(filepath, 'wb') as f:
            f.write(data)
        print(f'  Downloaded: {url[:60]}... -> {filename} ({len(data)//1024}KB)')
        return f'content/website/images/{filename}'
    except Exception as e:
        print(f'  FAILED: {url[:60]}... -> {e}')
        return None


def fix_srcset_in_html(html_path):
    if not os.path.exists(html_path):
        return False
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()
    new_html = re.sub(r'\s+srcset="[^"]*/assets/[^"]*"', '', html)
    if new_html != html:
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(new_html)
        return True
    return False


def translate_titles(titles_to_translate):
    sys.path.insert(0, '/Users/shanfu/cc/Library/Tools/common')
    sys.path.insert(0, '/Users/shanfu/cc/Library/Tools/postfdry/agents')
    try:
        from llm_utils import get_client, LLMProvider
        client = get_client()
    except Exception as e:
        print(f'  Cannot load LLM client: {e}')
        return {}

    results = {}
    for slug, title in titles_to_translate:
        if not title or title.strip() == '':
            continue
        prompt = f'''Translate the following English title to Chinese. Keep product names (Palantir, Foundry, Apollo, Gotham, AIP, ShipOS, Warp Speed, Vertex) in English. Output ONLY the Chinese translation, nothing else.

Title: {title}'''
        try:
            resp = client.generate_content(
                content=prompt,
                model_name='glm-5.2',
                provider=LLMProvider.DASHSCOPE,
                fallback=False
            )
            zh = resp.strip().strip('"').strip('\u201c').strip('\u201d')
            results[slug] = zh
            print(f'  Translated: {title[:40]}... -> {zh[:40]}...')
        except Exception as e:
            print(f'  FAILED to translate "{title[:30]}...": {e}')
    return results


def main():
    with open(WS_PATH, 'r', encoding='utf-8') as f:
        ws = json.load(f)

    articles = ws['articles']
    fixes = {'dates': 0, 'categories': 0, 'thumbnails': 0, 'srcset': 0, 'titles': 0}

    # Issue 3: Fix shareholder letter categorization
    print('\n=== Issue 3: Fix shareholder letter categorization ===')
    for a in articles:
        if a['s'] in LETTER_SLUGS_OTHER:
            old_bc = a.get('bc', [])
            if 'Other' in old_bc:
                a['bc'] = ['Newsroom']
                old_sc = a.get('sc', {})
                if 'Other' in old_sc:
                    old_sc['Newsroom'] = old_sc.pop('Other')
                    a['sc'] = old_sc
                fixes['categories'] += 1
                print(f'  Recategorized: {a["s"]}')

    # Issue 1: Extract dates
    print('\n=== Issue 1: Extract dates ===')
    for a in articles:
        if a.get('d'):
            continue
        slug = a['s']
        html_path = os.path.join(ROOT, 'content', 'website', slug, 'page.html')
        d = ''
        if os.path.exists(html_path):
            with open(html_path, 'r', encoding='utf-8') as f:
                html = f.read()
            d = extract_date_from_html(html)
        if not d:
            d = extract_date_from_slug(slug)
        if d:
            a['d'] = d
            fixes['dates'] += 1

    print(f'  Dates extracted: {fixes["dates"]}')
    no_date = sum(1 for a in articles if not a.get('d') and not a.get('hidden'))
    print(f'  Still no date (evergreen pages): {no_date}')

    # Issue 2: Download remote thumbnails
    print('\n=== Issue 2: Download remote thumbnails ===')
    for a in articles:
        th = a.get('th', '')
        if th.startswith('https://'):
            local_path = download_image(th)
            if local_path:
                a['th'] = local_path
                fixes['thumbnails'] += 1

    # Issue 4a: Fix broken srcset attributes
    print('\n=== Issue 4a: Fix broken srcset attributes ===')
    for a in articles:
        if a.get('hidden'):
            continue
        html_path = os.path.join(ROOT, 'content', 'website', a['s'], 'page.html')
        if fix_srcset_in_html(html_path):
            fixes['srcset'] += 1
    for a in articles:
        if a.get('hidden'):
            continue
        zh_path = os.path.join(ROOT, 'content', 'website', a['s'], 'page_zh.html')
        fix_srcset_in_html(zh_path)
    print(f'  srcset fixed in {fixes["srcset"]} page.html files')

    # Issue 4b: Translate missing titles
    print('\n=== Issue 4b: Translate missing titles ===')
    titles_to_translate = []
    for a in articles:
        if a.get('hidden'):
            continue
        if a.get('tt') == a.get('t') or not a.get('tt'):
            titles_to_translate.append((a['s'], a['t']))
    if titles_to_translate:
        print(f'  {len(titles_to_translate)} titles to translate')
        translations = translate_titles(titles_to_translate)
        for a in articles:
            if a['s'] in translations:
                a['tt'] = translations[a['s']]
                fixes['titles'] += 1

    with open(WS_PATH, 'w', encoding='utf-8') as f:
        json.dump(ws, f, ensure_ascii=False, indent=2)

    print(f'\n=== Summary ===')
    print(f'  Dates extracted: {fixes["dates"]}')
    print(f'  Categories fixed: {fixes["categories"]}')
    print(f'  Thumbnails downloaded: {fixes["thumbnails"]}')
    print(f'  srcset fixed: {fixes["srcset"]}')
    print(f'  Titles translated: {fixes["titles"]}')


if __name__ == '__main__':
    main()
