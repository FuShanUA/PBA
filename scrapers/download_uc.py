#!/usr/bin/env python3
"""
Palantir document auto-downloader (Skill).

Design principles (learned from trial and error):
1. ONE page at a time — batch mode triggers Google reCAPTCHA bans
2. Fresh Chrome profile per page — avoid fingerprint reuse
3. Human-like behavior — random delays, mouse movements, page reading time
4. reCAPTCHA strategy: click checkbox → if no challenge, submit → if challenge, try audio → if audio unavailable, skip
5. Cooldown tracking — record last attempt time, enforce min 60s between pages
6. Status file — track which pages are downloaded, which are pending, which are blocked

Usage:
  python3 scrapers/download_uc.py                    # Process next pending page
  python3 scrapers/download_uc.py --slug XXX         # Process specific page
  python3 scrapers/download_uc.py --status           # Show download status
  python3 scrapers/download_uc.py --all              # Process all pending (with 60s cooldown)
"""
import json, os, sys, time, random, argparse, subprocess, tempfile, shutil
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
os.chdir(ROOT)

WEBSITE_JSON = ROOT / "data" / "sources" / "website.json"
DOC_DIR = ROOT / "content" / "website" / "documents"
STATUS_FILE = ROOT / "data" / "download_status.json"
DOC_DIR.mkdir(parents=True, exist_ok=True)

FORM_PROFILE = {
    "FirstName": "Research",
    "LastName": "Analyst",
    "Email": "research.analyst@example.com",
    "Title": "Research Analyst",
    "Company": "Global Research Institute",
}

# --- Human behavior simulation ---

def human_delay(min_s=0.5, max_s=2.0):
    time.sleep(random.uniform(min_s, max_s))

def human_mouse_move(driver):
    from selenium.webdriver.common.action_chains import ActionChains
    try:
        actions = ActionChains(driver)
        actions.move_by_offset(random.randint(100, 800), random.randint(100, 600))
        actions.perform()
        human_delay(0.1, 0.5)
    except: pass

def human_click(driver, element):
    from selenium.webdriver.common.action_chains import ActionChains
    try:
        ActionChains(driver).move_to_element(element).perform()
        human_delay(0.3, 1.0)
        ActionChains(driver).move_to_element_with_offset(
            element, random.randint(-3, 3), random.randint(-3, 3)
        ).click().perform()
    except:
        element.click()

# --- Status management ---

def load_status():
    if STATUS_FILE.exists():
        with open(STATUS_FILE) as f:
            return json.load(f)
    return {}

def save_status(status):
    with open(STATUS_FILE, 'w') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)

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

# --- reCAPTCHA solver ---

def try_recaptcha(driver):
    """Try to solve reCAPTCHA v2. Returns True if solved."""
    from selenium.webdriver.common.by import By
    
    print("  Looking for reCAPTCHA...")
    
    # Find reCAPTCHA anchor iframe
    iframes = driver.find_elements(By.CSS_SELECTOR, 
        "iframe[src*='recaptcha/api2/anchor'], iframe[title*='reCAPTCHA']")
    
    for iframe in iframes:
        try:
            driver.switch_to.frame(iframe)
            human_delay(0.5, 1.0)
            
            checkbox = driver.find_element(By.ID, "recaptcha-anchor")
            if not checkbox.is_displayed():
                driver.switch_to.default_content()
                continue
            
            aria = checkbox.get_attribute("aria-checked")
            if aria == "true":
                print("  reCAPTCHA already solved")
                driver.switch_to.default_content()
                return True
            
            # Human-like click
            human_mouse_move(driver)
            human_delay(0.5, 1.5)
            human_click(driver, checkbox)
            print("  Clicked reCAPTCHA checkbox")
            human_delay(2.0, 4.0)
            
            # Check result
            aria = checkbox.get_attribute("aria-checked")
            if aria == "true":
                print("  SOLVED (no challenge)")
                driver.switch_to.default_content()
                return True
            
            print("  Challenge appeared, trying audio...")
            driver.switch_to.default_content()
            
            # Try audio challenge
            if try_audio_challenge(driver):
                return True
            
            # Retry checkbox (sometimes second click works)
            print("  Retrying checkbox...")
            human_delay(2.0, 4.0)
            for iframe2 in driver.find_elements(By.CSS_SELECTOR, "iframe[src*='recaptcha/api2/anchor']"):
                try:
                    driver.switch_to.frame(iframe2)
                    cb = driver.find_element(By.ID, "recaptcha-anchor")
                    if cb.is_displayed():
                        human_click(driver, cb)
                        human_delay(2.0, 4.0)
                        if cb.get_attribute("aria-checked") == "true":
                            print("  SOLVED on retry")
                            driver.switch_to.default_content()
                            return True
                    driver.switch_to.default_content()
                except:
                    driver.switch_to.default_content()
            
            return False
            
        except:
            driver.switch_to.default_content()
    
    print("  reCAPTCHA not found")
    return False

def try_audio_challenge(driver):
    """Try to solve reCAPTCHA audio challenge."""
    from selenium.webdriver.common.by import By
    import speech_recognition as sr
    
    # Find challenge iframe (bframe)
    bframes = driver.find_elements(By.CSS_SELECTOR, "iframe[src*='recaptcha/api2/bframe']")
    
    for bframe in bframes:
        try:
            driver.switch_to.frame(bframe)
            human_delay(1.0, 2.0)
            
            # Check if this is the challenge frame
            page_source = driver.page_source
            
            # Check for Google block message
            if "Try again later" in page_source or "automated queries" in page_source:
                print("  BLOCKED by Google (Try again later)")
                driver.switch_to.default_content()
                return False
            
            # Click audio button
            audio_clicked = False
            for selector in ["#recaptcha-audio-button", ".rc-button-goog", 
                           "button[aria-label*='audio']", "td#recaptcha-audio-button"]:
                try:
                    btn = driver.find_element(By.CSS_SELECTOR, selector)
                    if btn.is_displayed():
                        human_delay(0.5, 1.0)
                        human_click(driver, btn)
                        print("  Clicked audio button")
                        audio_clicked = True
                        human_delay(3.0, 5.0)
                        break
                except:
                    continue
            
            if not audio_clicked:
                # Maybe already on audio challenge
                pass
            
            # Wait for audio element (up to 15s)
            audio_src = None
            for wait_i in range(15):
                # Try various selectors for audio
                for selector in ["audio source", "audio", "#audio-source", 
                               "a.rc-audiochallenge-download-link", "a[href*='.mp3']",
                               "a[href*='google.com']"]:
                    try:
                        el = driver.find_element(By.CSS_SELECTOR, selector)
                        src = el.get_attribute("src") or el.get_attribute("href")
                        if src and ("mp3" in src or "audio" in src or "google" in src):
                            audio_src = src
                            break
                    except:
                        continue
                if audio_src:
                    break
                
                # Check for "Get audio challenge" button (might need another click)
                try:
                    get_audio = driver.find_element(By.CSS_SELECTOR, 
                        "a[href*='audio'], button[aria-label*='audio']")
                    if get_audio.is_displayed():
                        human_click(driver, get_audio)
                        human_delay(2.0, 4.0)
                except:
                    pass
                
                time.sleep(1)
            
            driver.switch_to.default_content()
            
            if not audio_src:
                print("  No audio source found (audio challenge may be unavailable)")
                return False
            
            print(f"  Audio: {audio_src[:80]}...")
            
            # Download audio
            tmp_audio = "/tmp/recaptcha_audio.mp3"
            subprocess.run(["curl", "-s", "-L", "-o", tmp_audio, audio_src], timeout=15)
            
            if not os.path.exists(tmp_audio) or os.path.getsize(tmp_audio) < 100:
                print("  Audio download failed")
                return False
            
            # Convert to WAV
            tmp_wav = "/tmp/recaptcha_audio.wav"
            try:
                from pydub import AudioSegment
                AudioSegment.from_mp3(tmp_audio).export(tmp_wav, format="wav")
            except:
                subprocess.run(["ffmpeg", "-y", "-i", tmp_audio, tmp_wav], 
                             capture_output=True, timeout=10)
            
            if not os.path.exists(tmp_wav):
                print("  Audio conversion failed")
                return False
            
            # Speech recognition
            r = sr.Recognizer()
            with sr.AudioFile(tmp_wav) as source:
                audio_data = r.record(source)
            
            try:
                text = r.recognize_google(audio_data).strip().lower()
                print(f"  Recognized: '{text}'")
            except sr.UnknownValueError:
                print("  Could not understand audio")
                return False
            except Exception as e:
                print(f"  Recognition error: {e}")
                return False
            
            # Enter answer
            driver.switch_to.frame(bframe)
            human_delay(0.5, 1.0)
            
            input_el = driver.find_element(By.ID, "audio-response")
            input_el.clear()
            for char in text:
                input_el.send_keys(char)
                human_delay(0.05, 0.15)
            
            human_delay(0.5, 1.0)
            
            verify_btn = driver.find_element(By.ID, "recaptcha-verify-button")
            human_click(driver, verify_btn)
            print("  Submitted audio answer")
            human_delay(2.0, 4.0)
            
            # Check if solved
            driver.switch_to.default_content()
            for anchor in driver.find_elements(By.CSS_SELECTOR, "iframe[src*='recaptcha/api2/anchor']"):
                try:
                    driver.switch_to.frame(anchor)
                    cb = driver.find_element(By.ID, "recaptcha-anchor")
                    if cb.get_attribute("aria-checked") == "true":
                        print("  SOLVED via audio!")
                        driver.switch_to.default_content()
                        return True
                    driver.switch_to.default_content()
                except:
                    driver.switch_to.default_content()
            
            print("  Audio answer rejected")
            return False
            
        except:
            driver.switch_to.default_content()
    
    return False

# --- Main download logic ---

def download_one(slug, url):
    """Download a document from a Palantir form page."""
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    
    # Fresh temp profile for each page
    profile_dir = tempfile.mkdtemp(prefix="uc_profile_")
    
    options = uc.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument(f"--user-data-dir={profile_dir}")
    
    options.add_experimental_option("prefs", {
        "download.default_directory": str(DOC_DIR),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "plugins.always_open_pdf_externally": True,
    })
    
    print(f"Launching Chrome (fresh profile)...")
    driver = uc.Chrome(options=options, version_main=None)
    driver.implicitly_wait(3)
    
    try:
        # Pre-set cookie consent
        driver.get("https://www.palantir.com")
        human_delay(2.0, 4.0)
        driver.add_cookie({
            "name": "OptanonConsent",
            "value": "isIABGlobal=false&datestamp=Mon+Jan+01+2024&version=6.10.0&groups=C0001%3A1%2CC0002%3A1%2CC0003%3A1%2CC0004%3A1",
            "domain": ".palantir.com",
            "path": "/",
        })
        
        print(f"Loading: {url}")
        driver.get(url)
        human_delay(3.0, 5.0)
        
        # Accept cookies if visible
        try:
            btn = driver.find_element(By.ID, "onetrust-accept-all-handler")
            if btn.is_displayed():
                human_click(driver, btn)
                print("Accepted cookies")
                human_delay(2.0, 3.0)
        except:
            try:
                for btn in driver.find_elements(By.CSS_SELECTOR, "button"):
                    if "Accept" in btn.text and btn.is_displayed():
                        human_click(driver, btn)
                        print("Accepted cookies (text)")
                        human_delay(2.0, 3.0)
                        break
            except: pass
        
        # Wait for form
        print("Waiting for Marketo form...")
        form_found = False
        for i in range(30):
            try:
                el = driver.find_element(By.ID, "FirstName")
                if el.is_displayed():
                    form_found = True
                    print(f"Form found at {i}s")
                    break
            except: pass
            time.sleep(1)
        
        if not form_found:
            print("ERROR: Form not found")
            return None, "form_not_found"
        
        # Human-like: read the page before filling
        print("Reading page (human-like)...")
        human_mouse_move(driver)
        human_delay(3.0, 6.0)
        
        # Fill form with human-like timing
        print("Filling form...")
        for field_id, value in FORM_PROFILE.items():
            try:
                el = driver.find_element(By.ID, field_id)
                human_click(driver, el)
                human_delay(0.2, 0.5)
                el.clear()
                for char in value:
                    el.send_keys(char)
                    human_delay(0.03, 0.08)
                print(f"  {field_id}")
                human_delay(0.3, 0.8)
            except Exception as e:
                print(f"  {field_id} FAILED: {e}")
        
        # Country
        try:
            from selenium.webdriver.support.ui import Select
            sel = Select(driver.find_element(By.ID, "Country__c_contact"))
            sel.select_by_visible_text("United States")
            print("  Country")
            human_delay(0.3, 0.8)
        except: pass
        
        # Opt-in
        for cb_id in ["Opt_In_Educational_Resources__c", "Opt_In_for_Future_Events__c"]:
            try:
                cb = driver.find_element(By.ID, cb_id)
                if not cb.is_selected():
                    human_click(driver, cb)
                    print(f"  {cb_id}")
                    human_delay(0.3, 0.8)
            except: pass
        
        # Solve reCAPTCHA
        print("Solving reCAPTCHA...")
        human_delay(1.0, 2.0)
        solved = try_recaptcha(driver)
        
        if not solved:
            print("reCAPTCHA not solved")
            return None, "recaptcha_failed"
        
        # Submit
        print("Submitting form...")
        human_delay(0.5, 1.5)
        try:
            btn = driver.find_element(By.CSS_SELECTOR, "button[type=submit], .mktoButton")
            human_click(driver, btn)
            print("Clicked submit")
        except:
            print("Submit button not found")
            return None, "no_submit_button"
        
        # Wait for result
        print("Waiting for result...")
        for i in range(30):
            time.sleep(1)
            try:
                body = driver.find_element(By.TAG_NAME, "body").text
                if "Thank you" in body or "Download" in body or "Success" in body:
                    print(f"Success at {i}s!")
                    break
            except: pass
            if i % 5 == 0:
                print(f"  {i}s...")
        
        # Wait for download
        time.sleep(5)
        
        # Find downloaded PDF (any recent PDF in DOC_DIR or Downloads)
        now = time.time()
        
        # Check DOC_DIR
        for p in DOC_DIR.glob("*.pdf"):
            if now - p.stat().st_mtime < 120 and p.stat().st_size > 1000:
                doc_path = f"content/website/documents/{p.name}"
                print(f"Downloaded: {doc_path}")
                return doc_path, None
        
        # Check Downloads folder
        for p in (Path.home() / "Downloads").glob("*.pdf"):
            if now - p.stat().st_mtime < 120 and p.stat().st_size > 1000:
                dest = DOC_DIR / p.name
                shutil.move(str(p), str(dest))
                doc_path = f"content/website/documents/{p.name}"
                print(f"Found in Downloads: {doc_path}")
                return doc_path, None
        
        # Check for download links on page
        try:
            links = driver.find_elements(By.CSS_SELECTOR, "a[href*='pdf'], a[href*='download']")
            for link in links:
                href = link.get_attribute("href")
                if href and (".pdf" in href.lower() or "download" in href.lower()):
                    if "png" in href or "jpg" in href:
                        continue
                    print(f"Downloading via link: {href[:80]}")
                    safe_name = f"{slug}.pdf"
                    local_path = DOC_DIR / safe_name
                    subprocess.run(["curl", "-s", "-L", "-o", str(local_path), href], timeout=30)
                    if local_path.exists() and local_path.stat().st_size > 1000:
                        doc_path = f"content/website/documents/{safe_name}"
                        print(f"Downloaded: {doc_path}")
                        return doc_path, None
        except: pass
        
        print("No PDF found after submission")
        print(f"URL: {driver.current_url}")
        body = driver.find_element(By.TAG_NAME, "body").text[:200]
        print(f"Body: {body}")
        return None, "no_pdf_found"
        
    except Exception as e:
        print(f"ERROR: {e}")
        return None, str(e)
    finally:
        try: driver.quit()
        except: pass
        # Clean up temp profile
        try: shutil.rmtree(profile_dir, ignore_errors=True)
        except: pass

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
    parser = argparse.ArgumentParser(description="Palantir document auto-downloader")
    parser.add_argument("--slug", help="Specific page slug")
    parser.add_argument("--all", action="store_true", help="Process all pending (with 60s cooldown)")
    parser.add_argument("--status", action="store_true", help="Show download status")
    args = parser.parse_args()
    
    if args.status:
        status = load_status()
        form_pages = detect_form_pages()
        with open(WEBSITE_JSON) as f:
            d = json.load(f)
        for a in d["articles"]:
            if a.get("doc_url"):
                print(f"  [DONE] {a['s']} -> {a['doc_url']}")
            elif a["s"] in [fp["s"] for fp in form_pages]:
                s = status.get(a["s"], {})
                last = s.get("last_attempt", "never")
                result = s.get("last_result", "pending")
                print(f"  [{result.upper()}] {a['s']} (last: {last})")
            else:
                continue
        return
    
    form_pages = detect_form_pages()
    if not form_pages:
        print("No pending form pages (all downloaded or none configured).")
        return
    
    print(f"Pending pages: {len(form_pages)}")
    for fp in form_pages:
        print(f"  {fp['s']}")
    
    if args.slug:
        targets = [fp for fp in form_pages if fp["s"] == args.slug]
    elif args.all:
        targets = form_pages
    else:
        # Process one at a time (recommended)
        targets = [form_pages[0]]
        print(f"\nProcessing next pending page: {targets[0]['s']}")
        print("(Use --all for batch mode with 60s cooldown)")
    
    status = load_status()
    
    for a in targets:
        slug = a["s"]
        url = a.get("u", f"https://www.palantir.com/{slug}/")
        
        # Check cooldown
        last_attempt = status.get(slug, {}).get("last_attempt_ts", 0)
        if last_attempt and time.time() - last_attempt < 60 and slug != (args.slug or ""):
            wait = int(60 - (time.time() - last_attempt))
            print(f"Cooling down for {slug}: {wait}s remaining...")
            time.sleep(wait)
        
        print(f"\n{'='*60}")
        print(f"Processing: {slug}")
        print(f"URL: {url}")
        print(f"Time: {datetime.now().isoformat()}")
        print(f"{'='*60}\n")
        
        doc_path, error = download_one(slug, url)
        
        # Update status
        status[slug] = {
            "last_attempt": datetime.now().isoformat(),
            "last_attempt_ts": time.time(),
            "last_result": "success" if doc_path else "failed",
            "last_error": error,
        }
        save_status(status)
        
        if doc_path:
            update_website_json(slug, doc_path)
            subprocess.run(["python3", "build.py"], cwd=str(ROOT))
            print(f"\nSUCCESS: {slug} -> {doc_path}")
        else:
            print(f"\nFAILED: {slug} ({error})")
            if error == "recaptcha_failed":
                print("reCAPTCHA could not be solved. Try again later (Google may have blocked).")
        
        # Cooldown between pages
        if len(targets) > 1:
            print("Cooling down 60s before next page...")
            time.sleep(60)
    
    print("\nDone!")

if __name__ == "__main__":
    main()
