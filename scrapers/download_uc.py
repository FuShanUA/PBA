#!/usr/bin/env python3
"""
Document downloader using undetected-chromedriver to bypass bot detection.
Palantir's site detects Playwright/Puppeteer and won't load Marketo forms.
undetected-chromedriver patches Chrome to avoid this detection.
"""
import json, os, sys, time, argparse, subprocess
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
    "Company": "Global Research Institute",
}

def detect_form_pages():
    form_list_path = ROOT / "data" / "form_pages.json"
    if form_list_path.exists():
        with open(form_list_path) as f:
            known = json.load(f)
    else:
        known = []
    with open(WEBSITE_JSON) as f:
        d = json.load(f)
    slug_to_article = {a["s"]: a for a in d["articles"]}
    form_pages = []
    for item in known:
        slug = item["slug"]
        a = slug_to_article.get(slug)
        if a and not a.get("hidden") and not a.get("doc_url"):
            a_copy = dict(a)
            a_copy["u"] = item.get("url", a.get("u", ""))
            form_pages.append(a_copy)
    return form_pages

def download_one(slug, url, buster_path=None):
    """Download a document from a Palantir form page using undetected-chromedriver."""
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    
    options = uc.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    
    if buster_path:
        options.add_argument("--disable-extensions-except=" + buster_path)
        options.add_argument("--load-extension=" + buster_path)
    
    # Set download directory
    options.add_experimental_option("prefs", {
        "download.default_directory": str(DOC_DIR),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    })
    
    print(f"Launching Chrome (undetected)...")
    driver = uc.Chrome(options=options, version_main=None)
    
    try:
        # Pre-set OneTrust cookie
        driver.get("https://www.palantir.com")
        time.sleep(2)
        
        driver.add_cookie({
            "name": "OptanonConsent",
            "value": "isIABGlobal=false&datestamp=Mon+Jan+01+2024&version=6.10.0&hosts=&consentId=&interactionCount=0&isGpcEnabled=0&browserGpcFlag=0&OTDataConsent=%5B%5D&groups=C0001%3A1%2CC0002%3A1%2CC0003%3A1%2CC0004%3A1",
            "domain": ".palantir.com",
            "path": "/",
        })
        
        print(f"Loading: {url}")
        driver.get(url)
        time.sleep(3)
        
        # Accept cookie consent if visible
        try:
            accept_btn = driver.find_element(By.ID, "onetrust-accept-all-handler")
            if accept_btn.is_displayed():
                accept_btn.click()
                print("Accepted cookies")
                time.sleep(2)
        except:
            try:
                buttons = driver.find_elements(By.CSS_SELECTOR, "button")
                for btn in buttons:
                    if "Accept" in btn.text and btn.is_displayed():
                        btn.click()
                        print("Accepted cookies (text)")
                        time.sleep(2)
                        break
            except:
                pass
        
        # Wait for Marketo form
        print("Waiting for Marketo form...")
        form_found = False
        for i in range(60):
            time.sleep(1)
            try:
                el = driver.find_element(By.ID, "FirstName")
                if el.is_displayed():
                    form_found = True
                    print(f"Form found at {i}s!")
                    break
            except:
                pass
            
            # Check iframes
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                try:
                    driver.switch_to.frame(iframe)
                    el = driver.find_element(By.ID, "FirstName")
                    if el.is_displayed():
                        form_found = True
                        print(f"Form found in iframe at {i}s!")
                        break
                    driver.switch_to.default_content()
                except:
                    driver.switch_to.default_content()
            
            if form_found:
                break
            
            if i % 10 == 0:
                title = driver.title
                has_mkto = "mktoweb" in driver.page_source
                has_recaptcha = "recaptcha" in driver.page_source.lower()
                has_cookie = "onetrust-banner-sdk" in driver.page_source
                print(f"  {i}s: title={title[:30]} mkto={has_mkto} recaptcha={has_recaptcha} cookie={has_cookie}")
        
        if not form_found:
            print(f"ERROR: Form never appeared")
            print(f"Title: {driver.title}")
            print(f"URL: {driver.current_url}")
            body = driver.find_element(By.TAG_NAME, "body").text[:200]
            print(f"Body: {body}")
            return None
        
        # Fill form
        print("Filling form...")
        for field_id, value in FORM_PROFILE.items():
            try:
                el = driver.find_element(By.ID, field_id)
                el.clear()
                el.send_keys(value)
                print(f"  Filled: {field_id}")
                time.sleep(0.2)
            except Exception as e:
                print(f"  Failed: {field_id} - {e}")
        
        # Country
        try:
            from selenium.webdriver.support.ui import Select
            sel = Select(driver.find_element(By.ID, "Country__c_contact"))
            sel.select_by_visible_text("United States")
            print("  Filled: Country")
        except Exception as e:
            print(f"  Failed: Country - {e}")
        
        # Opt-in
        for cb_id in ["Opt_In_Educational_Resources__c", "Opt_In_for_Future_Events__c"]:
            try:
                cb = driver.find_element(By.ID, cb_id)
                if not cb.is_selected():
                    cb.click()
                    print(f"  Checked: {cb_id}")
            except:
                pass
        
        print("Form filled. Waiting for CAPTCHA to be solved...")
        print("(Buster extension should auto-solve reCAPTCHA, or solve manually)")
        
        # Wait for form submission (up to 120s)
        submitted = False
        for i in range(120):
            time.sleep(1)
            
            # Check if form is gone
            try:
                form = driver.find_element(By.CSS_SELECTOR, "form.mktoForm, form")
                if not form.is_displayed():
                    submitted = True
                    print(f"Form submitted at {i}s!")
                    break
            except:
                # Form element not found = submitted
                submitted = True
                print(f"Form submitted at {i}s!")
                break
            
            # Check for thank-you text
            try:
                body = driver.find_element(By.TAG_NAME, "body").text
                if "Thank you" in body or "Download" in body or "Success" in body:
                    submitted = True
                    print(f"Thank-you page at {i}s!")
                    break
            except:
                pass
            
            # Try clicking submit every 10s
            if i > 5 and i % 10 == 0:
                try:
                    btn = driver.find_element(By.CSS_SELECTOR, "button[type=submit], .mktoButton")
                    if btn.is_displayed():
                        btn.click()
                        print(f"  Clicked submit at {i}s")
                except:
                    pass
            
            if i % 15 == 0 and i > 0:
                print(f"  Waiting for CAPTCHA... {i}s")
        
        # Wait for download
        print("Waiting for download...")
        time.sleep(10)
        
        # Check for downloaded files
        downloaded = list(DOC_DIR.glob(f"{slug}.*"))
        if downloaded:
            doc_path = f"content/website/documents/{downloaded[0].name}"
            print(f"Downloaded: {doc_path}")
            return doc_path
        
        # Check for PDF links on the page
        try:
            links = driver.find_elements(By.CSS_SELECTOR, "a[href*='pdf'], a[href*='download']")
            for link in links:
                href = link.get_attribute("href")
                if href and (".pdf" in href or "download" in href):
                    print(f"Found download link: {href}")
                    # Download via curl
                    safe_name = f"{slug}.pdf"
                    local_path = DOC_DIR / safe_name
                    subprocess.run(["curl", "-s", "-L", "-o", str(local_path), href], timeout=30)
                    if local_path.exists() and local_path.stat().st_size > 1000:
                        doc_path = f"content/website/documents/{safe_name}"
                        print(f"Downloaded: {doc_path}")
                        return doc_path
        except:
            pass
        
        print("No document downloaded")
        return None
        
    finally:
        driver.quit()

def update_website_json(slug, doc_path):
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
    parser = argparse.ArgumentParser(description="Download documents using undetected-chromedriver")
    parser.add_argument("--slug", help="Specific page slug")
    parser.add_argument("--all", action="store_true", help="Process all form pages")
    parser.add_argument("--no-buster", action="store_true", help="Don't load Buster extension")
    args = parser.parse_args()
    
    form_pages = detect_form_pages()
    if not form_pages:
        print("No form pages found.")
        return
    
    print(f"Found {len(form_pages)} pages with download forms:")
    for i, a in enumerate(form_pages):
        print(f"  [{i+1}] {a['s']}  ({a.get('t', '')[:50]})")
    
    if args.slug:
        targets = [a for a in form_pages if a["s"] == args.slug]
    elif args.all:
        targets = form_pages
    else:
        print("\nSelect pages (comma-separated, or 'all'):")
        choice = input("> ").strip()
        if choice.lower() == "all":
            targets = form_pages
        else:
            indices = [int(x.strip()) - 1 for x in choice.split(",") if x.strip().isdigit()]
            targets = [form_pages[i] for i in indices if 0 <= i < len(form_pages)]
    
    buster_path = None if args.no_buster else str(ROOT / "extensions" / "buster")
    
    print(f"\nProcessing {len(targets)} pages...")
    
    for a in targets:
        slug = a["s"]
        url = a.get("u", f"https://www.palantir.com/{slug}/")
        
        print(f"\n{'='*60}")
        print(f"Processing: {slug}")
        print(f"URL: {url}")
        print(f"{'='*60}\n")
        
        doc_path = download_one(slug, url, buster_path)
        
        if doc_path:
            update_website_json(slug, doc_path)
            subprocess.run(["python3", "build.py"], cwd=str(ROOT))
            print(f"\nSUCCESS: {slug}\n")
        else:
            print(f"\nFAILED: {slug}\n")
    
    print("Done!")

if __name__ == "__main__":
    main()
