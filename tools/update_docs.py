#!/usr/bin/env python3
"""Incremental updater for the English Palantir documentation archive."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITEMAP_PATH = os.path.join(ROOT, "data", "docs_sitemap.xml")
MANIFEST_PATH = os.path.join(ROOT, "data", "docs_manifest.json")
SUMMARY_PATH = os.path.join(ROOT, "data", "docs_update_summary.json")
ANNOUNCEMENTS_STATE_PATH = os.path.join(ROOT, "data", "docs_announcements.json")
COMPLETION_PATH = os.path.join(ROOT, "data", "docs_completion.json")
CONTENT_DIR = os.path.join(ROOT, "content", "docs")
ANNOUNCEMENTS_SLUG = "foundry-announcements"
ANNOUNCEMENTS_URL = "https://www.palantir.com/docs/foundry/announcements/"
PRODUCT_PREFIXES = ("/docs/foundry/", "/docs/apollo/", "/docs/gotham/")
STASH_SUFFIX = ".prev"
EXCLUDED_PATHS = {
    "/docs/foundry/",
    "/docs/apollo/",
    "/docs/gotham/",
    "/docs/foundry/search/",
    "/docs/apollo/search/",
    "/docs/gotham/search/",
}


def log(message):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def fetch_sitemap():
    url = "https://www.palantir.com/docs/sitemap.xml"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        xml = response.read().decode("utf-8")
    os.makedirs(os.path.dirname(SITEMAP_PATH), exist_ok=True)
    with open(SITEMAP_PATH, "w", encoding="utf-8") as f:
        f.write(xml)
    return xml


def parse_sitemap(xml):
    entries = {}
    for block in re.findall(r"<url>(.*?)</url>", xml, re.DOTALL):
        loc = re.search(r"<loc>(https?://[^<]+)</loc>", block)
        lastmod = re.search(r"<lastmod>([^<]+)</lastmod>", block)
        if not loc:
            continue
        parsed = urlparse(loc.group(1))
        path = parsed.path
        # Language sitemap entries only reveal the canonical English URL.
        # The localized page itself is never fetched.
        if path.startswith("/docs/zh/"):
            path = path.replace("/docs/zh/", "/docs/", 1)
        elif path.startswith(("/docs/jp/", "/docs/kr/")):
            continue
        path = path.rstrip("/") + "/"
        if not path.startswith(PRODUCT_PREFIXES) or path in EXCLUDED_PATHS:
            continue
        url = f"https://www.palantir.com{path}"
        slug = path.removeprefix("/docs/").rstrip("/").replace("/", "-")
        entries[slug] = {
            "url": url,
            "lastmod": lastmod.group(1) if lastmod else "",
        }
    return entries


def local_pages():
    pages = {}
    if not os.path.isdir(CONTENT_DIR):
        return pages
    for slug in os.listdir(CONTENT_DIR):
        meta_path = os.path.join(CONTENT_DIR, slug, "meta.json")
        page_path = os.path.join(CONTENT_DIR, slug, "page.html")
        if not os.path.isfile(meta_path) or not os.path.isfile(page_path):
            continue
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            continue
        url = meta.get("url", "")
        parsed = urlparse(url)
        if parsed.netloc not in ("palantir.com", "www.palantir.com"):
            continue
        path = parsed.path.rstrip("/") + "/"
        canonical_url = f"https://www.palantir.com{path}"
        expected_slug = path.removeprefix("/docs/").rstrip("/").replace("/", "-")
        if expected_slug == slug and path.startswith(PRODUCT_PREFIXES):
            pages[slug] = canonical_url
    return pages


def file_digest(path):
    if not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def recover_stashed_pages():
    """Put back any page left in a stash by an interrupted run."""
    if not os.path.isdir(CONTENT_DIR):
        return 0
    recovered = 0
    for slug in os.listdir(CONTENT_DIR):
        page_dir = os.path.join(CONTENT_DIR, slug)
        if not os.path.isdir(page_dir):
            continue
        for filename in ("page.html", "page_zh.html"):
            stash = os.path.join(page_dir, filename + STASH_SUFFIX)
            if not os.path.isfile(stash):
                continue
            live = os.path.join(page_dir, filename)
            if os.path.isfile(live):
                os.remove(stash)
            else:
                os.replace(stash, live)
                recovered += 1
    return recovered


def stash_changed_pages(slugs):
    """Move the current copies aside so the fetcher treats them as missing.

    Returns {slug: digest of the previous page.html}. Deleting the files
    outright lost every page whose re-fetch failed, and forced a full
    re-translation even when the page body had not moved.
    """
    stashed = {}
    for slug in slugs:
        page = os.path.join(CONTENT_DIR, slug, "page.html")
        zh = os.path.join(CONTENT_DIR, slug, "page_zh.html")
        digest = file_digest(page)
        moved = False
        if os.path.isfile(page):
            os.replace(page, page + STASH_SUFFIX)
            moved = True
        if os.path.isfile(zh):
            os.replace(zh, zh + STASH_SUFFIX)
            moved = True
        if moved or digest:
            stashed[slug] = digest
    return stashed


def resolve_stashed_pages(stashed):
    """Compare each re-fetched page against its stash and clean up.

    Identical bodies keep the existing translation, so a sitemap-wide
    lastmod bump no longer costs a full re-translation. A page that did not
    come back is restored from the stash instead of being left empty.
    """
    identical = set()
    restored = set()
    for slug, digest in stashed.items():
        page = os.path.join(CONTENT_DIR, slug, "page.html")
        zh = os.path.join(CONTENT_DIR, slug, "page_zh.html")
        page_prev = page + STASH_SUFFIX
        zh_prev = zh + STASH_SUFFIX
        if not os.path.isfile(page):
            if os.path.isfile(page_prev):
                os.replace(page_prev, page)
                restored.add(slug)
            if os.path.isfile(zh_prev):
                os.replace(zh_prev, zh)
            continue
        if digest and file_digest(page) == digest:
            identical.add(slug)
            if os.path.isfile(zh_prev) and not os.path.isfile(zh):
                os.replace(zh_prev, zh)
        if os.path.isfile(page_prev):
            os.remove(page_prev)
        if os.path.isfile(zh_prev):
            os.remove(zh_prev)
    return identical, restored


def load_manifest():
    if not os.path.exists(MANIFEST_PATH):
        return {"source": "docs", "last_scan": "", "entries": {}}
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("entries", {})
    return data


def load_unavailable_slugs(max_age_seconds=86400):
    if not os.path.exists(COMPLETION_PATH):
        return set()
    if time.time() - os.stat(COMPLETION_PATH).st_mtime > max_age_seconds:
        return set()
    try:
        with open(COMPLETION_PATH, encoding="utf-8") as f:
            completion = json.load(f)
    except Exception:
        return set()
    unavailable = set()
    for failure in completion.get("failures", []):
        url = failure[0] if isinstance(failure, list) else failure.get("url", "")
        status = failure[1] if isinstance(failure, list) else failure.get("status", "")
        if status != "no-content":
            continue
        path = urlparse(url).path
        slug = path.removeprefix("/docs/").rstrip("/").replace("/", "-")
        if slug:
            unavailable.add(slug)
    return unavailable


def save_manifest(manifest, sitemap_entries, pages, unavailable_slugs, stale_slugs=()):
    now = datetime.now(timezone.utc).isoformat()
    entries = manifest.setdefault("entries", {})
    for slug, url in pages.items():
        info = sitemap_entries.get(slug, {})
        entry = entries.setdefault(slug, {})
        # A page restored from its stash after a failed fetch still holds the
        # older revision, so keep the older lastmod and retry it on a later run.
        if slug in stale_slugs:
            lastmod = entry.get("lastmod", "")
        else:
            lastmod = info.get("lastmod", entry.get("lastmod", ""))
        entry.update(
            {
                "url": url,
                "lastmod": lastmod,
                "status": "ok",
                "last_checked": now,
            }
        )
    for slug, info in sitemap_entries.items():
        if slug in pages:
            continue
        entry = entries.setdefault(slug, {})
        entry.update(
            {
                "url": info["url"],
                "lastmod": info.get("lastmod", ""),
                "status": "unavailable" if slug in unavailable_slugs else entry.get("status", "missing"),
                "last_checked": now,
            }
        )
    manifest["last_scan"] = now
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")


def run_command(command, label):
    log(f"{label}...")
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    for line in process.stdout:
        if line.strip():
            log(line.rstrip())
    process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"{label} failed: exit code {process.returncode}")


def missing_translation_count():
    missing = 0
    for slug in local_pages():
        zh_path = os.path.join(CONTENT_DIR, slug, "page_zh.html")
        if not (os.path.isfile(zh_path) and os.path.getsize(zh_path) > 200):
            missing += 1
    return missing


def read_audit_count():
    path = os.path.join(ROOT, "data", "translation_audit.json")
    try:
        with open(path, encoding="utf-8") as f:
            return int(json.load(f).get("count", 0))
    except Exception:
        return None


def parse_announcement_entries(path):
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    container = soup.select_one("div.ptcom-design__markdownDoc__1uarhel") or soup.body
    if container is None:
        return []

    entries = []
    for heading in container.find_all("h2"):
        title = heading.get_text(" ", strip=True)
        if not title:
            continue
        date_paragraph = heading.find_next_sibling("p")
        date_text = date_paragraph.get_text(" ", strip=True) if date_paragraph else ""
        date_match = re.search(r"Date published:\s*(\d{4}-\d{2}-\d{2})", date_text)
        if not date_match:
            continue

        anchor = ""
        link = heading.find("a", href=True)
        if link and link.get("href", "").startswith("#"):
            anchor = link["href"]
        elif heading.get("id"):
            anchor = "#" + heading["id"]
        url = ANNOUNCEMENTS_URL + anchor if anchor else ANNOUNCEMENTS_URL
        entries.append(
            {
                "title": title,
                "date": date_match.group(1),
                "url": url,
            }
        )
    return entries


def translated_announcement_titles(path):
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    container = soup.select_one("div.ptcom-design__markdownDoc__1uarhel") or soup.body
    if container is None:
        return {}

    titles = {}
    for heading in container.find_all("h2"):
        link = heading.find("a", href=True)
        anchor = ""
        if link and link.get("href", "").startswith("#"):
            anchor = link["href"]
        elif heading.get("id"):
            anchor = "#" + heading["id"]
        if anchor:
            titles[anchor] = heading.get_text(" ", strip=True)
    return titles


def load_announcement_state():
    local_path = os.path.join(CONTENT_DIR, ANNOUNCEMENTS_SLUG, "page.html")
    if os.path.isfile(ANNOUNCEMENTS_STATE_PATH):
        with open(ANNOUNCEMENTS_STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)
        state.setdefault("entries", [])
        return state
    return {"entries": parse_announcement_entries(local_path)}


def collect_new_announcements():
    state = load_announcement_state()
    known = {(entry["title"], entry["date"]) for entry in state["entries"]}
    current = parse_announcement_entries(
        os.path.join(CONTENT_DIR, ANNOUNCEMENTS_SLUG, "page.html")
    )
    translated_titles = translated_announcement_titles(
        os.path.join(CONTENT_DIR, ANNOUNCEMENTS_SLUG, "page_zh.html")
    )
    for entry in current:
        anchor = entry["url"].removeprefix(ANNOUNCEMENTS_URL)
        if anchor in translated_titles:
            entry["title_zh"] = translated_titles[anchor]
    new_entries = [
        entry for entry in current if (entry["title"], entry["date"]) not in known
    ]
    state["entries"] = current
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(ANNOUNCEMENTS_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return new_entries


def update_docs(workers=3, translate=True):
    recovered = recover_stashed_pages()
    if recovered:
        log(f"Recovered {recovered} page(s) left in a stash by an earlier run")
    xml = fetch_sitemap()
    sitemap_entries = parse_sitemap(xml)
    before = local_pages()
    manifest = load_manifest()
    first_run = not manifest.get("entries")
    recent_unavailable = load_unavailable_slugs()
    for slug in recent_unavailable:
        if slug not in sitemap_entries or slug in before:
            continue
        entry = manifest["entries"].setdefault(slug, {})
        if entry.get("status") != "ok":
            entry.setdefault("lastmod", sitemap_entries[slug].get("lastmod", ""))
            entry["status"] = "unavailable"

    new_candidates = []
    for slug, info in sitemap_entries.items():
        if slug in before:
            continue
        entry = manifest["entries"].get(slug, {})
        same_unavailable = (
            entry.get("status") == "unavailable"
            and entry.get("lastmod") == info.get("lastmod", "")
        )
        if not same_unavailable:
            new_candidates.append(slug)
    changed_candidates = []
    if not first_run:
        for slug in sitemap_entries:
            if slug not in before:
                continue
            old_lastmod = manifest["entries"].get(slug, {}).get("lastmod", "")
            new_lastmod = sitemap_entries[slug].get("lastmod", "")
            if new_lastmod and old_lastmod and new_lastmod != old_lastmod:
                changed_candidates.append(slug)

    # Palantir rewrites <lastmod> across the whole sitemap on every docs
    # release, so a lastmod diff says nothing about the page body. Stash the
    # current files rather than deleting them, then compare after the fetch.
    stashed = stash_changed_pages(changed_candidates)

    log(
        f"Docs sitemap: {len(sitemap_entries)} English pages; "
        f"new={len(new_candidates)} changed={len(changed_candidates)}"
    )

    fetch_updates = bool(new_candidates or changed_candidates)
    if fetch_updates:
        run_command(
            [sys.executable, os.path.join(ROOT, "complete_docs.py"), "--workers", str(workers)],
            "Fetching new and changed documentation",
        )
        run_command([sys.executable, os.path.join(ROOT, "gen_docs_json.py")], "Rebuilding docs index")
    else:
        log("No documentation updates found.")

    restored = set()
    if stashed:
        identical, restored = resolve_stashed_pages(stashed)
        changed_candidates = [
            slug for slug in changed_candidates if slug not in identical and slug not in restored
        ]
        log(
            f"Re-checked {len(stashed)} changed candidate(s): "
            f"{len(identical)} byte-identical (translation kept), "
            f"{len(restored)} restored after a failed fetch, "
            f"{len(changed_candidates)} genuinely changed"
        )

    missing_before = missing_translation_count()
    translation = {
        "enabled": translate,
        "status": "skipped" if not translate else "not-run",
        "missing_before": missing_before,
    }
    if translate:
        translation_error = None
        try:
            run_command(
                [
                    sys.executable,
                    os.path.join(ROOT, "tools", "translation_forever.py"),
                    "--workers",
                    str(workers),
                    "--max-rounds",
                    "5",
                ],
                "Translating documentation",
            )
        except RuntimeError as e:
            translation_error = str(e)
            log(f"Documentation translation failed: {translation_error}")

        # Refresh titles after translation even when a round fails, because
        # completed pages should still become visible in the index.
        run_command(
            [sys.executable, os.path.join(ROOT, "gen_docs_json.py")],
            "Refreshing docs index after translation",
        )
        run_command(
            [
                sys.executable,
                os.path.join(ROOT, "tools", "audit_partial_translations.py"),
                "--output",
                "data/translation_audit.json",
            ],
            "Auditing documentation translations",
        )
        missing_after = missing_translation_count()
        audit_count = read_audit_count()
        translation.update(
            {
                "status": (
                    "failed"
                    if translation_error or missing_after or audit_count is None or audit_count
                    else "ok"
                ),
                "missing_after": missing_after,
                "translated": max(0, missing_before - missing_after),
                "audit_count": audit_count,
            }
        )
        if translation_error:
            translation["error"] = translation_error

    after = local_pages()
    new_slugs = sorted(set(after) - set(before))
    changed_slugs = [slug for slug in changed_candidates if slug in after]
    unavailable_slugs = load_unavailable_slugs()
    announcement_updates = collect_new_announcements()
    save_manifest(manifest, sitemap_entries, after, unavailable_slugs, restored)

    summary = {
        "new": len(new_slugs),
        "changed": len(changed_slugs),
        "announcement_count": len(announcement_updates),
        "announcement_updates": announcement_updates,
        "new_slugs": new_slugs,
        "changed_slugs": changed_slugs,
        "has_updates": bool(new_slugs or changed_slugs or announcement_updates),
        "translation": translation,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--no-translate", action="store_true")
    args = parser.parse_args()
    summary = update_docs(args.workers, translate=not args.no_translate)
    log(
        f"Docs update complete: new={summary['new']} changed={summary['changed']} "
        f"translation={summary['translation']['status']}"
    )


if __name__ == "__main__":
    main()
