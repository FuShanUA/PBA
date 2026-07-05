#!/usr/bin/env python3
"""
Semi-automated document downloader for Palantir pages with Marketo forms + reCAPTCHA.

Usage:
  python3 scrapers/download_documents.py                    # Interactive: pick pages
  python3 scrapers/download_documents.py --slug 2025-ai-ds-ml-market-study  # Specific page
  python3 scrapers/download_documents.py --all              # All detected form pages

Workflow:
  1. Detects pages with download forms (Marketo + reCAPTCHA)
  2. Opens each page in a HEADFUL browser (visible window)
  3. Pre-fills form fields automatically
  4. User manually solves reCAPTCHA and clicks Submit
  5. Script captures any PDF/download URLs from network traffic
  6. Downloads and saves the document to content/website/documents/{slug}.pdf
  7. Updates website.json with doc_url field
"""

import json, os, re, sys, time, argparse, subprocess
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

def detect_form_pages():
    """Find website articles whose pages contain Marketo forms."""
    with open(WEBSITE_JSON) as f:
        d = json.load(f)
    
    form_pages = []
    for a in d["articles"]:
        if a.get("hidden"):
            continue
        slug = a["s"]
        page_path = ROOT / "content" / "website" / slug / "page.html"
        if not page_path.exists():
            continue
        html = page_path.read_text(encoding="utf-8")
        # Check for Marketo form indicators
        if "mkto" in html.lower() or "mktoweb" in html.lower() or "formId" in html:
            # Also check if already has a document downloaded
            if a.get("doc_url"):
                continue
            form_pages.append(a)
    
    return form_pages

def download_with_playwright(slug, url):
    """Open page in headful browser, pre-fill form, wait for user to submit."""
    script = f"""
const {{ chromium }} = require('playwright');
(async () => {{
  const browser = await chromium.launch({{ headless: false }});
  const page = await browser.newPage();
  
  const downloadUrls = [];
  const pdfUrls = [];
  
  // Capture downloads
  page.on('download', async download => {{
    const name = download.suggestedFilename();
    console.log('DOWNLOAD:' + name);
    const path = '{DOC_DIR}/{slug}' + '.' + name.split('.').pop();
    await download.saveAs(path);
    console.log('SAVED:' + path);
  }});
  
  // Capture PDF/asset responses
  page.on('response', resp => {{
    const u = resp.url();
    const ct = resp.headers()['content-type'] || '';
    if (ct.includes('pdf') || u.endsWith('.pdf') || (u.includes('/assets/') && ct.includes('application'))) {{
      pdfUrls.push(u);
      console.log('PDF_URL:' + u);
    }}
  }});
  
  // Capture navigation to thank-you pages
  page.on('framenavigated', frame => {{
    const u = frame.url();
    if (u.includes('thank') || u.includes('download') || u.includes('success')) {{
      console.log('NAV:' + u);
    }}
  }});
  
  await page.goto('{url}', {{ waitUntil: 'domcontentloaded', timeout: 30000 }});
  await page.waitForTimeout(5000);
  
  // Pre-fill form
  const fields = {json.dumps(FORM_PROFILE)};
  for (const [id, value] of Object.entries(fields)) {{
    try {{
      const el = page.locator('#' + id);
      if (await el.isVisible({{ timeout: 1000 }})) {{
        if (el.tagName === 'SELECT' || (await el.evaluate(e => e.tagName === 'SELECT'))) {{
          await el.selectOption(value);
        }} else {{
          await el.fill(value);
        }}
        console.log('FILLED:' + id);
      }}
    }} catch {{}}
  }}
  
  // Check opt-in boxes
  for (const id of ['Opt_In_Educational_Resources__c', 'Opt_In_for_Future_Events__c']) {{
    try {{
      await page.locator('#' + id).check({{ timeout: 1000 }});
      console.log('CHECKED:' + id);
    }} catch {{}}
  }}
  
  console.log('FORM_FILLED: Please solve reCAPTCHA and click Submit.');
  console.log('Waiting for form submission... (timeout: 120s)');
  
  // Wait for form to disappear (submission successful) or timeout
  try {{
    await page.waitForFunction(() => !document.querySelector('form') || document.body.innerText.includes('Thank you') || document.body.innerText.includes('Download'), {{ timeout: 120000 }});
    console.log('FORM_SUBMITTED');
    
    // Wait a bit for any redirects/downloads
    await page.waitForTimeout(5000);
    
    // Check for download links on the page
    const links = await page.evaluate(() => {{
      return Array.from(document.querySelectorAll('a[href]'))
        .filter(a => a.href.includes('pdf') || a.href.includes('download') || a.href.includes('asset'))
        .map(a => ({{ href: a.href, text: a.textContent.trim() }}));
    }});
    if (links.length > 0) {{
      console.log('LINKS:' + JSON.stringify(links));
    }}
    
    // Check for any PDF URLs captured
    if (pdfUrls.length > 0) {{
      console.log('PDF_URLS:' + JSON.stringify(pdfUrls));
    }}
  }} catch (e) {{
    console.log('TIMEOUT: Form not submitted within 120s');
  }}
  
  // Keep browser open for a moment in case download is still in progress
  await page.waitForTimeout(3000);
  await browser.close();
}})();
"""
    
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True, text=True, timeout=180, cwd=str(ROOT)
    )
    
    output = result.stdout + result.stderr
    print(output)
    
    # Parse output for saved file
    saved_path = None
    for line in output.split("\n"):
        if line.startswith("SAVED:"):
            saved_path = line[6:]
        elif line.startswith("PDF_URL:") or line.startswith("PDF_URLS:"):
            pdf_url = line.split(":", 1)[1].strip().strip('"[]')
            if pdf_url and pdf_url.startswith("http"):
                # Download the PDF
                safe_name = slug + ".pdf"
                local_path = DOC_DIR / safe_name
                subprocess.run(["curl", "-s", "-L", "-o", str(local_path), pdf_url], timeout=30)
                if local_path.exists() and local_path.stat().st_size > 1000:
                    saved_path = f"content/website/documents/{safe_name}"
                    print(f"Downloaded PDF: {saved_path}")
    
    return saved_path

def update_website_json(slug, doc_path):
    """Update website.json with doc_url for the given slug."""
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
    elif args.all:
        targets = form_pages
    else:
        # Interactive selection
        print("\nSelect pages to process (comma-separated numbers, or 'all'):")
        choice = input("> ").strip()
        if choice.lower() == "all":
            targets = form_pages
        else:
            indices = [int(x.strip()) - 1 for x in choice.split(",") if x.strip().isdigit()]
            targets = [form_pages[i] for i in indices if 0 <= i < len(form_pages)]
    
    print(f"\nProcessing {len(targets)} pages...")
    
    for a in targets:
        slug = a["s"]
        url = a.get("u", f"https://www.palantir.com/{slug}/")
        
        print(f"\n{'='*60}")
        print(f"Processing: {slug}")
        print(f"URL: {url}")
        print(f"Title: {a.get('t', '')}")
        print(f"{'='*60}")
        
        doc_path = download_with_playwright(slug, url)
        
        if doc_path:
            update_website_json(slug, doc_path)
            print(f"SUCCESS: Document saved for {slug}")
        else:
            print(f"FAILED: No document downloaded for {slug}")
    
    print("\nDone!")

if __name__ == "__main__":
    main()
