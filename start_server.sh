#!/bin/bash
echo "SCRIPT STARTED at $(date)" >> /tmp/palantir_debug.log
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export HOME=/Users/shanfu
cd /Users/shanfu/Desktop/palantir-blog-archive
echo "ABOUT TO START PYTHON at $(date)" >> /tmp/palantir_debug.log
.venv/bin/python3 server.py --port 8765 >> /tmp/palantir_debug.log 2>&1
echo "PYTHON EXITED with code $? at $(date)" >> /tmp/palantir_debug.log
