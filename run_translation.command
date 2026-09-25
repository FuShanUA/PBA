#!/bin/zsh
cd /Users/shanfu/Desktop/palantir-blog-archive

if ! pgrep -f "tools/TranslationProgressPopup" >/dev/null; then
  nohup tools/TranslationProgressPopup \
    data/translation_progress.json \
    data/translation_node_events.jsonl \
    data/translation_request_events.jsonl \
    content/docs \
    >/dev/null 2>&1 &
fi

if ! pgrep -f "tools/translation_forever.py" >/dev/null; then
  nohup python3 tools/translation_forever.py --workers 3 \
    >data/translation.log 2>&1 &
fi
