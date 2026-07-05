#!/usr/bin/env python3
"""
Automated document downloader for Palantir pages with Marketo forms + reCAPTCHA.

Supports three CAPTCHA-solving strategies:
  1. --method extension  : Use Chrome with your installed reCAPTCHA solver plugins
  2. --method load-ext   : Load a specific extension from a path
  3. --method manual     : Headful browser, solve CAPTCHA by hand (default)

Usage:
  python3 scrapers/download_documents.py                              # List form pages
  python3 scrapers/download_documents.py --slug 2025-ai-ds-ml-market-study
  python3 scrapers/download_documents.py --slug 2025-ai-ds-ml-market-study --method extension
  python3 scrapers/download_documents.py --slug 2025-ai-ds-ml-market-study --method load-ext --ext-path ~/Downloads/buster
  python3 scrapers/download_documents.py --all --method extension
"""

import json, os, re, sys, time, argparse, subprocess, tempfile, shutil
from pathlib import Path

ROOT = Path(__file__).parent.parent
os.chdir(ROOT)

WEBSITE_JSON = ROOT / "data" / "sources" / "website.json"
DOC_DIR = ROOT / "content" / "website" / "documents"
DOC_DIR.mkdir(parents=True, exist_ok=True)

FORM_PROFILE = {
    "FirstName": "Research",
    "LastName": "Analyst",
    "Email": "research.analyst@example.com",
    "Title": "Research Analyst",
    "Company": "Independent Research Institute",
    "Country__c_contact": "United States",
}

# Chrome user data dir locations (macOS)
CHROME_PROFILES = [
    os.path.expanduser("~/Library/Application Support/Google/Chrome"),
    os.path.expanduser("~/Library/Application Support/Google/Chrome/Default"),
]

def detect_form_pages():
    """Return known pages with Marketo download forms.
    
    Marketo forms are JS-rendered and cannot be detected from static HTML.
    This list is maintained manually based on Playwright verification.
    """
    form_list_path = ROOT / "data" / "form_pages.json"
    if form_list_path.exists():
        with open(form_list_path) as f:
            known = json.load(f)
    else:
        known = []
    
    # Load website.json to get full article data
    with open(WEBSITE_JSON) as f:
        d = json.load(f)
    slug_to_article = {a["s"]: a for a in d["articles"]}
    
    form_pages = []
    for item in known:
        slug = item["slug"]
        a = slug_to_article.get(slug)
        if a and not a.get("hidden") and not a.get("doc_url"):
            # Merge known info with article data
            a_copy = dict(a)
            a_copy["u"] = item.get("url", a.get("u", ""))
            form_pages.append(a_copy)
    
    return form_pages

def build_node_script(slug, url, method, ext_path=None):
    """Build the Node.js Playwright script."""
    
    if method == "extension":
        profile_src = os.path.expanduser("~/Library/Application Support/Google/Chrome")
        profile_dst = tempfile.mkdtemp(prefix="chrome_profile_")
        ext_src = os.path.join(profile_src, "Default", "Extensions")
        if os.path.exists(ext_src):
            ext_dst = os.path.join(profile_dst, "Default", "Extensions")
            os.makedirs(os.path.dirname(ext_dst), exist_ok=True)
            shutil.copytree(ext_src, ext_dst, dirs_exist_ok=True)
        launch_opts = {
            "channel": "chrome",
            "headless": False,
            "userDataDir": profile_dst,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--disable-default-apps",
            ],
        }
    elif method == "load-ext":
        launch_opts = {
            "headless": False,
            "args": [
                "--disable-extensions-except=" + (ext_path or ""),
                "--load-extension=" + (ext_path or ""),
                "--disable-blink-features=AutomationControlled",
            ],
        }
    elif method == "buster":
        # Load Buster reCAPTCHA solver extension
        buster_path = str(ROOT / "extensions" / "buster")
        launch_opts = {
            "headless": False,
            "args": [
                "--disable-extensions-except=" + buster_path,
                "--load-extension=" + buster_path,
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
            ],
        }
    else:
        launch_opts = {
            "headless": False,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
    
    opts_json = json.dumps(launch_opts)
    profile_json = json.dumps(FORM_PROFILE)
    doc_dir = str(DOC_DIR)
    
    # Use plain string with .replace() to avoid f-string brace conflicts
    template = '''const { chromium } = require('playwright');
(async () => {
  const opts = __OPTS__;
  let browser, page;
  if (opts.userDataDir) {
    const ud = opts.userDataDir;
    delete opts.userDataDir;
    browser = await chromium.launchPersistentContext(ud, opts);
    page = await browser.newPage();
  } else {
    browser = await chromium.launch(opts);
    page = await browser.newPage();
  }
  
  const pdfUrls = [];
  let savedFile = null;
  
  page.on('download', async download => {
    const name = download.suggestedFilename();
    console.log('DOWNLOAD:' + name);
    const ext = name.split('.').pop();
    const path = '__DOC_DIR__/__SLUG__.' + ext;
    await download.saveAs(path);
    savedFile = path;
    console.log('SAVED:' + path);
  });
  
  page.on('response', resp => {
    const u = resp.url();
    const ct = resp.headers()['content-type'] || '';
    if (ct.includes('pdf') || u.endsWith('.pdf')) {
      pdfUrls.push(u);
      console.log('PDF_RESPONSE:' + u.substring(0, 200));
    }
  });
  
  page.on('framenavigated', frame => {
    const u = frame.url();
    if (u.includes('thank') || u.includes('download') || u.includes('success')) {
      console.log('NAV:' + u);
    }
  });
  
  console.log('Loading: __URL__');
  await page.goto('__URL__', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(5000);
  
  // Pre-fill form
  const fields = __PROFILE__;
  for (const [id, value] of Object.entries(fields)) {
    try {
      const el = page.locator('#' + id);
      if (await el.isVisible({ timeout: 2000 })) {
        const tag = await el.evaluate(e => e.tagName);
        if (tag === 'SELECT') await el.selectOption(value);
        else await el.fill(value);
        console.log('FILLED:' + id);
      }
    } catch(e) {}
  }
  
  for (const id of ['Opt_In_Educational_Resources__c', 'Opt_In_for_Future_Events__c']) {
    try { await page.locator('#' + id).check({ timeout: 2000 }); console.log('CHECKED:' + id); } catch {}
  }
  
  const method = '__METHOD__';
  
  if (method === 'extension' || method === 'load-ext' || method === 'buster') {
    console.log('WAITING_FOR_CAPTCHA: Extension should solve reCAPTCHA...');
    let captchaSolved = false;
    for (let i = 0; i < 60; i++) {
      await page.waitForTimeout(1000);
      const solved = await page.evaluate(() => {
        const formGone = !document.querySelector('form');
        const thankYou = document.body.innerText.includes('Thank you') || 
                         document.body.innerText.includes('Download');
        return formGone || thankYou;
      }).catch(() => false);
      if (solved) { captchaSolved = true; console.log('CAPTCHA_SOLVED'); break; }
      if (i > 3 && i % 5 === 0) {
        try {
          const btn = page.locator('button[type=submit], .mktoButton').first();
          if (await btn.isVisible({ timeout: 500 })) { await btn.click(); console.log('CLICK_SUBMIT'); }
        } catch {}
      }
    }
    if (!captchaSolved) {
      try {
        const btn = page.locator('button[type=submit], .mktoButton').first();
        if (await btn.isVisible({ timeout: 1000 })) { await btn.click(); console.log('FINAL_SUBMIT'); }
      } catch {}
    }
  } else {
    console.log('MANUAL: Please solve reCAPTCHA and click Submit.');
  }
  
  console.log('WAITING_FOR_RESULT...');
  try {
    await page.waitForFunction(() => {
      return !document.querySelector('form') || 
             document.body.innerText.includes('Thank you') ||
             document.body.innerText.includes('Download');
    }, { timeout: 60000 });
    console.log('FORM_SUBMITTED');
  } catch { console.log('TIMEOUT_WAITING'); }
  
  await page.waitForTimeout(5000);
  
  const links = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('a[href]'))
      .filter(a => a.href.includes('pdf') || a.href.includes('download') || 
                   (a.href.includes('asset') && !a.href.includes('.png') && !a.href.includes('.jpg')))
      .map(a => ({ href: a.href, text: a.textContent.trim() }));
  }).catch(() => []);
  
  if (links.length > 0) console.log('LINKS:' + JSON.stringify(links));
  if (pdfUrls.length > 0) console.log('PDF_URLS:' + JSON.stringify(pdfUrls));
  if (savedFile) console.log('RESULT:' + savedFile);
  
  await browser.close();
})();
'''
    
    script = template
    script = script.replace('__OPTS__', opts_json)
    script = script.replace('__PROFILE__', profile_json)
    script = script.replace('__DOC_DIR__', doc_dir)
    script = script.replace('__SLUG__', slug)
    script = script.replace('__URL__', url)
    script = script.replace('__METHOD__', method)
    
    return script


def download_with_playwright(slug, url, method="manual", ext_path=None):
    """Run the Playwright script and return the saved document path."""
    script = build_node_script(slug, url, method, ext_path)
    
    # Write script to temp file
    script_path = ROOT / f"scrapers/_dl_{slug}.js"
    script_path.write_text(script)
    
    try:
        result = subprocess.run(
            ["node", str(script_path)],
            capture_output=True, text=True, timeout=180, cwd=str(ROOT)
        )
        output = result.stdout + result.stderr
        print(output)
        
        # Parse output
        saved_path = None
        for line in output.split("\n"):
            if line.startswith("SAVED:"):
                saved_path = line[6:].strip()
            elif line.startswith("RESULT:"):
                saved_path = line[7:].strip()
            elif line.startswith("PDF_URLS:"):
                urls_json = line[9:].strip()
                try:
                    urls = json.loads(urls_json)
                    for pdf_url in urls:
                        safe_name = f"{slug}.pdf"
                        local_path = DOC_DIR / safe_name
                        subprocess.run(["curl", "-s", "-L", "-o", str(local_path), pdf_url], timeout=30)
                        if local_path.exists() and local_path.stat().st_size > 1000:
                            saved_path = f"content/website/documents/{safe_name}"
                            print(f"Downloaded PDF: {saved_path}")
                except:
                    pass
            elif line.startswith("LINKS:"):
                links_json = line[6:].strip()
                try:
                    links = json.loads(links_json)
                    for link in links:
                        href = link.get("href", "")
                        if href.endswith(".pdf") or "pdf" in href.lower():
                            safe_name = f"{slug}.pdf"
                            local_path = DOC_DIR / safe_name
                            subprocess.run(["curl", "-s", "-L", "-o", str(local_path), href], timeout=30)
                            if local_path.exists() and local_path.stat().st_size > 1000:
                                saved_path = f"content/website/documents/{safe_name}"
                                print(f"Downloaded PDF from link: {saved_path}")
                except:
                    pass
        
        return saved_path
    finally:
        script_path.unlink(missing_ok=True)

def update_website_json(slug, doc_path):
    """Update website.json with doc_url."""
    with open(WEBSITE_JSON) as f:
        d = json.load(f)
    for a in d["articles"]:
        if a["s"] == slug:
            a["doc_url"] = doc_path
            print(f"Updated {slug}: doc_url = {doc_path}")
            break
    with open(WEBSITE_JSON, "w") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"))

def main():
    parser = argparse.ArgumentParser(description="Download documents from Palantir form pages")
    parser.add_argument("--slug", help="Specific page slug to process")
    parser.add_argument("--all", action="store_true", help="Process all detected form pages")
    parser.add_argument("--method", choices=["manual", "extension", "load-ext", "buster"], default="buster",
                        help="CAPTCHA solving method: manual (default), extension (Chrome with plugins), load-ext (load specific extension)")
    parser.add_argument("--ext-path", help="Path to extension directory (for load-ext method)")
    args = parser.parse_args()
    
    form_pages = detect_form_pages()
    
    if not form_pages:
        print("No pages with download forms found (or all already have documents).")
        return
    
    print(f"Found {len(form_pages)} pages with download forms:")
    for i, a in enumerate(form_pages):
        print(f"  [{i+1}] {a['s']}  ({a.get('t', '')[:50]})")
    
    if args.slug:
        targets = [a for a in form_pages if a["s"] == args.slug]
        if not targets:
            print(f"Slug '{args.slug}' not found in form pages.")
            return
    elif args.all:
        targets = form_pages
    else:
        print("\nSelect pages to process (comma-separated numbers, or 'all'):")
        choice = input("> ").strip()
        if choice.lower() == "all":
            targets = form_pages
        else:
            indices = [int(x.strip()) - 1 for x in choice.split(",") if x.strip().isdigit()]
            targets = [form_pages[i] for i in indices if 0 <= i < len(form_pages)]
    
    print(f"\nMethod: {args.method}")
    if args.ext_path:
        print(f"Extension path: {args.ext_path}")
    print(f"Processing {len(targets)} pages...\n")
    
    for a in targets:
        slug = a["s"]
        url = a.get("u", f"https://www.palantir.com/{slug}/")
        
        print(f"{'='*60}")
        print(f"Processing: {slug}")
        print(f"URL: {url}")
        print(f"Title: {a.get('t', '')}")
        print(f"{'='*60}\n")
        
        doc_path = download_with_playwright(slug, url, args.method, args.ext_path)
        
        if doc_path:
            update_website_json(slug, doc_path)
            print(f"\nSUCCESS: Document saved for {slug}\n")
        else:
            print(f"\nFAILED: No document downloaded for {slug}\n")
        
        # Rebuild index after each download
        subprocess.run(["python3", "build.py"], cwd=str(ROOT))
    
    print("Done!")

if __name__ == "__main__":
    main()
