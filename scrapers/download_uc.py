#!/usr/bin/env python3
"""
Fully automatic document downloader:
1. Uses undetected_chromedriver to bypass bot detection
2. Auto-fills Marketo form
3. Auto-solves reCAPTCHA v2 (click checkbox, or audio challenge + speech recognition)
4. Submits form and downloads PDF
"""
import json, os, sys, time, argparse, subprocess, tempfile, hashlib
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

def solve_recaptcha_audio(driver):
    """Try to solve reCAPTCHA v2 audio challenge using speech recognition."""
    import speech_recognition as sr
    from pydub import AudioSegment
    from selenium.webdriver.common.by import By
    
    # Find the audio challenge iframe
    iframes = driver.find_elements(By.CSS_SELECTOR, "iframe[src*='recaptcha/api2/bframe']")
    for iframe in iframes:
        try:
            driver.switch_to.frame(iframe)
            time.sleep(1)
            
            # Click audio button if present
            try:
                audio_btn = driver.find_element(By.ID, "recaptcha-audio-button")
                if audio_btn.is_displayed():
                    audio_btn.click()
                    print("  Clicked audio button")
                    time.sleep(2)
            except:
                try:
                    # Try alternative selectors
                    btns = driver.find_elements(By.CSS_SELECTOR, "button[aria-label*='audio'], .rc-button-goog")
                    for btn in btns:
                        if btn.is_displayed():
                            btn.click()
                            print("  Clicked audio button (alt)")
                            time.sleep(2)
                            break
                except:
                    pass
            
            # Get audio source
            try:
                audio_el = driver.find_element(By.CSS_SELECTOR, "audio source, audio")
                audio_src = audio_el.get_attribute("src")
                if audio_src:
                    print(f"  Audio source: {audio_src[:80]}...")
                    
                    # Download audio file
                    tmp_audio = "/tmp/recaptcha_audio.mp3"
                    subprocess.run(["curl", "-s", "-L", "-o", tmp_audio, audio_src], timeout=15)
                    
                    if os.path.exists(tmp_audio) and os.path.getsize(tmp_audio) > 100:
                        # Convert to WAV
                        tmp_wav = "/tmp/recaptcha_audio.wav"
                        try:
                            audio = AudioSegment.from_mp3(tmp_audio)
                            audio.export(tmp_wav, format="wav")
                        except:
                            # Try direct conversion
                            subprocess.run(["ffmpeg", "-y", "-i", tmp_audio, tmp_wav], 
                                         capture_output=True, timeout=10)
                        
                        # Recognize speech
                        if os.path.exists(tmp_wav):
                            r = sr.Recognizer()
                            with sr.AudioFile(tmp_wav) as source:
                                audio_data = r.record(source)
                            try:
                                text = r.recognize_google(audio_data)
                                print(f"  Speech recognized: '{text}'")
                                
                                # Enter the answer
                                input_el = driver.find_element(By.ID, "audio-response")
                                input_el.clear()
                                input_el.send_keys(text.lower())
                                time.sleep(0.5)
                                
                                # Click verify
                                verify_btn = driver.find_element(By.ID, "recaptcha-verify-button")
                                verify_btn.click()
                                print("  Submitted audio answer")
                                time.sleep(3)
                                
                                driver.switch_to.default_content()
                                return True
                            except sr.UnknownValueError:
                                print("  Could not understand audio")
                            except Exception as e:
                                print(f"  Recognition error: {e}")
                    else:
                        print("  Audio download failed")
            except Exception as e:
                print(f"  Audio element error: {e}")
            
            driver.switch_to.default_content()
        except:
            driver.switch_to.default_content()
    
    return False

def click_recaptcha_checkbox(driver):
    """Click the reCAPTCHA v2 checkbox. Returns True if solved without challenge."""
    from selenium.webdriver.common.by import By
    
    # Find reCAPTCHA anchor iframe
    iframes = driver.find_elements(By.CSS_SELECTOR, "iframe[src*='recaptcha/api2/anchor'], iframe[title*='reCAPTCHA']")
    for iframe in iframes:
        try:
            driver.switch_to.frame(iframe)
            time.sleep(0.5)
            
            # Click the checkbox
            checkbox = driver.find_element(By.ID, "recaptcha-anchor")
            if checkbox.is_displayed():
                aria_checked = checkbox.get_attribute("aria-checked")
                if aria_checked != "true":
                    checkbox.click()
                    print("  Clicked reCAPTCHA checkbox")
                    time.sleep(3)
                    
                    # Check if solved (no challenge appeared)
                    aria_checked = checkbox.get_attribute("aria-checked")
                    if aria_checked == "true":
                        print("  reCAPTCHA SOLVED (no challenge)")
                        driver.switch_to.default_content()
                        return True
                    else:
                        print("  Challenge appeared")
                        driver.switch_to.default_content()
                        return False
                else:
                    print("  reCAPTCHA already solved")
                    driver.switch_to.default_content()
                    return True
        except:
            pass
        finally:
            driver.switch_to.default_content()
    
    return False

def download_one(slug, url):
    """Download a document from a Palantir form page."""
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    
    options = uc.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    
    options.add_experimental_option("prefs", {
        "download.default_directory": str(DOC_DIR),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "plugins.always_open_pdf_externally": True,
    })
    
    print(f"Launching Chrome (undetected)...")
    driver = uc.Chrome(options=options, version_main=None)
    driver.implicitly_wait(3)
    
    try:
        # Pre-set cookie consent
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
                btns = driver.find_elements(By.CSS_SELECTOR, "button")
                for btn in btns:
                    if "Accept" in btn.text and btn.is_displayed():
                        btn.click()
                        print("Accepted cookies (text)")
                        time.sleep(2)
                        break
            except:
                pass
        
        # Wait for form
        print("Waiting for Marketo form...")
        form_found = False
        for i in range(30):
            try:
                el = driver.find_element(By.ID, "FirstName")
                if el.is_displayed():
                    form_found = True
                    print(f"Form found at {i}s!")
                    break
            except:
                pass
            time.sleep(1)
            if i % 5 == 0:
                has_mkto = "mktoweb" in driver.page_source
                print(f"  {i}s: mkto={has_mkto}")
        
        if not form_found:
            print(f"ERROR: Form not found. Title: {driver.title}")
            return None
        
        # Fill form
        print("Filling form...")
        for field_id, value in FORM_PROFILE.items():
            try:
                el = driver.find_element(By.ID, field_id)
                el.clear()
                el.send_keys(value)
                print(f"  {field_id} = {value}")
                time.sleep(0.2)
            except Exception as e:
                print(f"  {field_id} FAILED: {e}")
        
        # Country
        try:
            from selenium.webdriver.support.ui import Select
            sel = Select(driver.find_element(By.ID, "Country__c_contact"))
            sel.select_by_visible_text("United States")
            print("  Country = United States")
        except:
            pass
        
        # Opt-in
        for cb_id in ["Opt_In_Educational_Resources__c", "Opt_In_for_Future_Events__c"]:
            try:
                cb = driver.find_element(By.ID, cb_id)
                if not cb.is_selected():
                    cb.click()
                    print(f"  {cb_id} checked")
            except:
                pass
        
        # Solve reCAPTCHA
        print("Solving reCAPTCHA...")
        time.sleep(2)
        
        # Try clicking the checkbox first (might pass without challenge)
        solved = click_recaptcha_checkbox(driver)
        
        if not solved:
            # Try audio challenge
            print("Trying audio challenge...")
            solved = solve_recaptcha_audio(driver)
        
        if not solved:
            # Retry checkbox click (sometimes second attempt works)
            print("Retrying checkbox...")
            time.sleep(2)
            solved = click_recaptcha_checkbox(driver)
        
        if not solved:
            # One more audio attempt
            print("Retrying audio...")
            solved = solve_recaptcha_audio(driver)
        
        print(f"reCAPTCHA solved: {solved}")
        
        # Submit form
        print("Submitting form...")
        try:
            btn = driver.find_element(By.CSS_SELECTOR, "button[type=submit], .mktoButton")
            btn.click()
            print("Clicked submit")
        except:
            print("Submit button not found")
        
        # Wait for submission
        print("Waiting for submission result...")
        submitted = False
        for i in range(30):
            time.sleep(1)
            try:
                body = driver.find_element(By.TAG_NAME, "body").text
                if "Thank you" in body or "Download" in body or "Success" in body:
                    submitted = True
                    print(f"Success at {i}s!")
                    break
            except:
                pass
            if i % 5 == 0:
                print(f"  Waiting... {i}s")
        
        # Check for downloads
        time.sleep(5)
        
        # Check DOC_DIR for any new PDF (Chrome saves with original filename)
        all_pdfs = list(DOC_DIR.glob("*.pdf"))
        # Find PDFs that were downloaded in the last 60 seconds
        import time as _time
        now = _time.time()
        recent_pdfs = [p for p in all_pdfs if now - p.stat().st_mtime < 60]
        if recent_pdfs:
            pdf = recent_pdfs[0]
            doc_path = f"content/website/documents/{pdf.name}"
            print(f"Downloaded: {doc_path}")
            return doc_path
        
        # Check Downloads folder for recent PDFs
        downloads_dir = Path.home() / "Downloads"
        for f in downloads_dir.glob("*.pdf"):
            if now - f.stat().st_mtime < 60 and f.stat().st_size > 1000:
                dest = DOC_DIR / f.name
                import shutil
                shutil.move(str(f), str(dest))
                doc_path = f"content/website/documents/{f.name}"
                print(f"Found in Downloads: {doc_path}")
                return doc_path
        
        # Check for download links
        try:
            links = driver.find_elements(By.CSS_SELECTOR, "a[href*='pdf'], a[href*='download']")
            for link in links:
                href = link.get_attribute("href")
                if href and ".pdf" in href.lower():
                    print(f"Downloading: {href}")
                    safe_name = f"{slug}.pdf"
                    local_path = DOC_DIR / safe_name
                    subprocess.run(["curl", "-s", "-L", "-o", str(local_path), href], timeout=30)
                    if local_path.exists() and local_path.stat().st_size > 1000:
                        doc_path = f"content/website/documents/{safe_name}"
                        print(f"Downloaded: {doc_path}")
                        return doc_path
        except:
            pass
        
        # Debug
        print(f"URL: {driver.current_url}")
        print(f"Title: {driver.title}")
        body = driver.find_element(By.TAG_NAME, "body").text[:300]
        print(f"Body: {body}")
        
        return None
        
    finally:
        driver.quit()

def update_website_json(slug, doc_path):
    with open(WEBSITE_JSON) as f:
        d = json.load(f)
    for a in d["articles"]:
        if a["s"] == slug:
            a["doc_url"] = doc_path
            break
    with open(WEBSITE_JSON, "w") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"))

def main():
    parser = argparse.ArgumentParser(description="Auto-download documents (undetected_chromedriver + reCAPTCHA solver)")
    parser.add_argument("--slug", help="Specific page slug")
    parser.add_argument("--all", action="store_true", help="Process all form pages")
    args = parser.parse_args()
    
    form_pages = detect_form_pages()
    if not form_pages:
        print("No form pages found.")
        return
    
    print(f"Found {len(form_pages)} pages:")
    for i, a in enumerate(form_pages):
        print(f"  [{i+1}] {a['s']}")
    
    if args.slug:
        targets = [a for a in form_pages if a["s"] == args.slug]
    elif args.all:
        targets = form_pages
    else:
        print("Select (comma-separated, or 'all'):")
        choice = input("> ").strip()
        if choice.lower() == "all":
            targets = form_pages
        else:
            indices = [int(x.strip()) - 1 for x in choice.split(",") if x.strip().isdigit()]
            targets = [form_pages[i] for i in indices if 0 <= i < len(form_pages)]
    
    for a in targets:
        slug = a["s"]
        url = a.get("u", f"https://www.palantir.com/{slug}/")
        print(f"\n{'='*60}")
        print(f"Processing: {slug}")
        print(f"{'='*60}\n")
        
        doc_path = download_one(slug, url)
        if doc_path:
            update_website_json(slug, doc_path)
            subprocess.run(["python3", "build.py"], cwd=str(ROOT))
            print(f"SUCCESS: {slug}")
        else:
            print(f"FAILED: {slug}")
    
    print("\nDone!")

if __name__ == "__main__":
    main()
