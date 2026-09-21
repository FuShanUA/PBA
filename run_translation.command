#!/bin/zsh
cd /Users/shanfu/Desktop/palantir-blog-archive
if ! pgrep -f "tools/TranslationProgressPopup" >/dev/null; then
  tools/TranslationProgressPopup data/translation_progress.json &
fi
exec python3 tools/translation_forever.py --workers 3
