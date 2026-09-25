#!/usr/bin/env python3
"""Run document translation rounds until every page has a Chinese version."""

import argparse
import glob
import os
import signal
import subprocess
import sys
import time

from audit_partial_translations import audit_page


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRANSLATOR = os.path.join(ROOT, "scrapers", "translate_parallel.py")
CONTENT_DIR = os.path.join(ROOT, "content", "docs")
PROGRESS_PATH = os.path.join(ROOT, "data", "translation_progress.json")
NODE_EVENTS_PATH = os.path.join(ROOT, "data", "translation_node_events.jsonl")
REQUEST_EVENTS_PATH = os.path.join(ROOT, "data", "translation_request_events.jsonl")
CACHE_GLOB = os.path.join(ROOT, "data", "translation_cache", "*.json")


def missing_count():
    missing = 0
    for entry in os.listdir(CONTENT_DIR):
        page_dir = os.path.join(CONTENT_DIR, entry)
        english = os.path.join(page_dir, "page.html")
        chinese = os.path.join(page_dir, "page_zh.html")
        if not os.path.isfile(english):
            continue
        if not (os.path.isfile(chinese) and os.path.getsize(chinese) > 200):
            missing += 1
    return missing


def latest_activity():
    paths = [PROGRESS_PATH, NODE_EVENTS_PATH, REQUEST_EVENTS_PATH] + glob.glob(CACHE_GLOB)
    return max((os.path.getmtime(path) for path in paths if os.path.exists(path)), default=time.time())


def partial_pages():
    partial = []
    for entry in os.listdir(CONTENT_DIR):
        page_dir = os.path.join(CONTENT_DIR, entry)
        en_path = os.path.join(page_dir, "page.html")
        zh_path = os.path.join(page_dir, "page_zh.html")
        if not os.path.isfile(en_path):
            continue
        finding = audit_page(en_path, zh_path)
        if finding and finding.get("reason") != "missing":
            partial.append(finding["slug"])
    return partial


def stop_process(process):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_round(workers, stall_seconds):
    command = [sys.executable, "-u", TRANSLATOR, "--workers", str(workers)]
    process = subprocess.Popen(command, cwd=ROOT)
    last_activity = time.time()

    try:
        while process.poll() is None:
            time.sleep(10)
            activity = latest_activity()
            if activity > last_activity:
                last_activity = activity
                continue
            if time.time() - last_activity >= stall_seconds:
                print(
                    f"[Supervisor] no file activity for {stall_seconds}s; restarting round",
                    flush=True,
                )
                stop_process(process)
                return
    except KeyboardInterrupt:
        stop_process(process)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--stall-seconds", type=int, default=900)
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=0,
        help="Stop after this many rounds; 0 means retry until complete",
    )
    args = parser.parse_args()

    rounds = 0
    while True:
        missing = missing_count()
        print(f"[Supervisor] missing={missing}", flush=True)
        if missing == 0:
            partial = partial_pages()
            if partial:
                print(
                    f"[Supervisor] partial translations={len(partial)}; removing and retrying",
                    flush=True,
                )
                for slug in partial:
                    zh_path = os.path.join(CONTENT_DIR, slug, "page_zh.html")
                    if os.path.exists(zh_path):
                        os.remove(zh_path)
                continue
            print("[Supervisor] all documents translated", flush=True)
            return 0
        rounds += 1
        if args.max_rounds and rounds > args.max_rounds:
            print(
                f"[Supervisor] stopped after {args.max_rounds} rounds; "
                f"{missing} pages remain untranslated",
                flush=True,
            )
            return 1
        run_round(args.workers, args.stall_seconds)
        time.sleep(2)


if __name__ == "__main__":
    sys.exit(main())
