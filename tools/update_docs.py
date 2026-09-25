#!/usr/bin/env python3
"""Incremental updater for the English Palantir documentation archive."""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITEMAP_PATH = os.path.join(ROOT, "data", "docs_sitemap.xml")
MANIFEST_PATH = os.path.join(ROOT, "data", "docs_manifest.json")
SUMMARY_PATH = os.path.join(ROOT, "data", "docs_update_summary.json")
COMPLETION_PATH = os.path.join(ROOT, "data", "docs_completion.json")
CONTENT_DIR = os.path.join(ROOT, "content", "docs")
PRODUCT_PREFIXES = ("/docs/foundry/", "/docs/apollo/", "/docs/gotham/")
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


def save_manifest(manifest, sitemap_entries, pages, unavailable_slugs):
    now = datetime.now(timezone.utc).isoformat()
    entries = manifest.setdefault("entries", {})
    for slug, url in pages.items():
        info = sitemap_entries.get(slug, {})
        entry = entries.setdefault(slug, {})
        entry.update(
            {
                "url": url,
                "lastmod": info.get("lastmod", entry.get("lastmod", "")),
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
    process = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    for line in process.stdout.splitlines():
        if line.strip():
            log(line)
    if process.returncode != 0:
        raise RuntimeError(f"{label} failed: {process.stderr[-500:]}")


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


def update_docs(workers=3, translate=True):
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

    for slug in changed_candidates:
        for filename in ("page.html", "page_zh.html"):
            path = os.path.join(CONTENT_DIR, slug, filename)
            if os.path.exists(path):
                os.remove(path)

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
    save_manifest(manifest, sitemap_entries, after, unavailable_slugs)

    summary = {
        "new": len(new_slugs),
        "changed": len(changed_slugs),
        "new_slugs": new_slugs,
        "changed_slugs": changed_slugs,
        "has_updates": bool(new_slugs or changed_slugs),
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
