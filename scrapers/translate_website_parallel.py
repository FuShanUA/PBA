#!/usr/bin/env python3
"""Run the docs translation pipeline against website pages."""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scrapers"))

import translate_parallel as pipeline


pipeline.CONTENT_DIR = str(ROOT / "content" / "website")
pipeline.CACHE_DIR = str(ROOT / "data" / "website_translation_cache")
pipeline.PROGRESS_PATH = str(ROOT / "data" / "website_translation_progress.json")
pipeline.NODE_EVENTS_PATH = str(ROOT / "data" / "website_translation_node_events.jsonl")
pipeline.REQUEST_EVENTS_PATH = str(ROOT / "data" / "website_translation_request_events.jsonl")
pipeline.ARTICLE_FALLBACK_TO_BODY = True
pipeline.ARTICLE_FORCE_BODY = True
pipeline.REMOVE_FORM_SECTIONS = True


def load_slugs(path):
    if path == "-":
        return [line.strip() for line in sys.stdin if line.strip()]
    return [line.strip() for line in Path(path).read_text().splitlines() if line.strip()]


def write_progress(total, completed, errors, started_at):
    payload = {
        "total": total,
        "completed": completed,
        "errors": errors,
        "remaining": total - completed - errors,
        "elapsed_seconds": round(time.time() - started_at),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    output = Path(pipeline.PROGRESS_PATH)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slugs-file", required=True)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument(
        "--model",
        default=pipeline.MODEL,
        help="translation model for this website run (default: %(default)s)",
    )
    args = parser.parse_args()

    slugs = load_slugs(args.slugs_file)
    if not slugs:
        raise SystemExit("No slugs supplied")

    client = pipeline.get_client()
    pipeline.MODEL = args.model
    pipeline.reset_node_events()
    pipeline.reset_request_events()

    completed = 0
    errors = 0
    started_at = time.time()
    write_progress(len(slugs), completed, errors, started_at)
    print(f"Translating {len(slugs)} website pages with {args.workers} workers", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(pipeline.translate_one_slug, slug, client): slug
            for slug in slugs
        }
        for future in as_completed(futures):
            slug = futures[future]
            try:
                result_slug, success, detail = future.result()
                status = "OK" if success else "FAIL"
            except Exception as exc:
                result_slug, success, detail = slug, False, str(exc)[:120]
                status = "FAIL"
            if success:
                completed += 1
            else:
                errors += 1
            print(f"{status} {result_slug}: {detail}", flush=True)
            write_progress(len(slugs), completed, errors, started_at)

    print(
        f"Done: completed={completed} errors={errors} "
        f"elapsed={round(time.time() - started_at)}s",
        flush=True,
    )
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
