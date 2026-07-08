#!/usr/bin/env python3
"""Build script: merges all source JSONs in data/sources/ into a unified data/index.json."""

import json, os, glob

ROOT = os.path.dirname(os.path.abspath(__file__))
SOURCES_DIR = os.path.join(ROOT, "data", "sources")
OUTPUT_PATH = os.path.join(ROOT, "data", "index.json")

def load_sources():
    """Load all source JSON files from data/sources/."""
    sources = {}
    for path in sorted(glob.glob(os.path.join(SOURCES_DIR, "*.json"))):
        name = os.path.splitext(os.path.basename(path))[0]
        with open(path, "r", encoding="utf-8") as f:
            sources[name] = json.load(f)
    return sources

def build_index(sources):
    """Merge all sources into a unified index."""
    all_articles = []
    all_pending = []
    bc_counts = {}
    sc_counts = {}
    dt = {}
    tag_freq = {}
    cat_hierarchy = {}
    tag_zh = {}
    source_meta = {}

    for source_name, source_data in sources.items():
        articles = source_data.get("articles", [])
        visible = [a for a in articles if not a.get("hidden", False) and not a.get("pending", False)]
        pending = [a for a in articles if a.get("pending", False) and not a.get("hidden", False)]
        source_meta[source_name] = {
            "source_name": source_data.get("source_name", source_name),
            "source_name_zh": source_data.get("source_name_zh", source_name),
            "count": len(visible),
            "pending": len(pending),
            "last_scan": source_data.get("last_scan", ""),
        }

        for a in visible:
            a["source"] = source_name
            # Map doc_url to short key "du" for the UI
            if a.get("doc_url"):
                a["du"] = a["doc_url"]

        all_articles.extend(visible)
        all_pending.extend([{"s": a["s"], "t": a.get("t",""), "tt": a.get("tt",""), "u": a.get("u",""),
                             "th": a.get("th",""), "ds": a.get("ds",""), "d": a.get("d",""),
                             "bc": a.get("bc",[]), "source": source_name,
                             "hp": a.get("hp","")} for a in pending])

        for cat, count in source_data.get("bc", {}).items():
            bc_counts[cat] = bc_counts.get(cat, 0) + count
        for key, count in source_data.get("tag_freq", {}).items():
            tag_freq[key] = tag_freq.get(key, 0) + count
        for cat, subs in source_data.get("sc", {}).items():
            if cat not in sc_counts:
                sc_counts[cat] = {}
            for sub, count in subs.items():
                sc_counts[cat][sub] = sc_counts[cat].get(sub, 0) + count
        for cat, info in source_data.get("cat_hierarchy", {}).items():
            if cat not in cat_hierarchy:
                cat_hierarchy[cat] = info
            else:
                existing = set(cat_hierarchy[cat].get("subcats", []))
                for sc in info.get("subcats", []):
                    if sc not in existing:
                        cat_hierarchy[cat]["subcats"].append(sc)
                        existing.add(sc)
        for k, v in source_data.get("tag_zh", {}).items():
            tag_zh[k] = v
        for year, months in source_data.get("dt", {}).items():
            if year not in dt:
                dt[year] = {}
            for month, count in months.items():
                dt[year][month] = dt[year].get(month, 0) + count

    all_articles.sort(key=lambda a: a.get("d", ""), reverse=True)

    index = {
        "total": len(all_articles),
        "sources": source_meta,
        "articles": all_articles,
        "pending": all_pending,
        "bc": bc_counts,
        "sc": sc_counts,
        "dt": dt,
        "tag_freq": tag_freq,
        "cat_hierarchy": cat_hierarchy,
        "tag_zh": tag_zh,
    }
    return index

def main():
    sources = load_sources()
    if not sources:
        print("No source files found in data/sources/")
        return

    print(f"Loaded {len(sources)} sources: {', '.join(sources.keys())}")
    index = build_index(sources)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(OUTPUT_PATH) / 1024
    print(f"Built data/index.json: {index['total']} articles, {size_kb:.0f}KB")
    for name, meta in index["sources"].items():
        print(f"  {name}: {meta['count']} articles")

if __name__ == "__main__":
    main()
