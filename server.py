#!/usr/bin/env python3
"""Lightweight dev server for the Palantir blog archive.

Serves static files (index.html, data/, articles/, content/) on the root,
plus a JSON API at /api/* for the content-update UI:

  GET  /api/status            -> current source counts + last-scan times
  POST /api/update            -> stream SSE progress while scanning sources
                                 body: {"sources":["blog","website"], "translate":true}

Run:  python3 server.py [--port 8765] [--host 0.0.0.0]
"""

import json, os, sys, threading, queue, time, urllib.parse, argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import scan_api

# Lock so only one update runs at a time
_update_lock = threading.Lock()
_update_running = {"active": False}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # quiet

    def _send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_review(self):
        """Handle review actions: approve, exclude, delete pending articles.
        Body: {"action":"approve"|"exclude"|"delete", "slugs":["slug1","slug2"], "source":"website"}
        """
        length = int(self.headers.get("Content-Length", 0))
        try:
            raw = self.rfile.read(length) if length > 0 else b"{}"
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._send_json(400, {"error": "invalid JSON body"})
            return
        action = body.get("action", "")
        slugs = body.get("slugs", [])
        source = body.get("source", "website")
        if action not in ("approve", "exclude", "delete") or not slugs:
            self._send_json(400, {"error": "need action and slugs"})
            return
        try:
            result = scan_api.review_pending(source, slugs, action)
            self._send_json(200, result)
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _serve_file(self, rel_path):
        # Prevent path traversal
        safe = os.path.normpath(os.path.join(ROOT, rel_path))
        if not safe.startswith(ROOT):
            self._send_json(403, {"error": "forbidden"})
            return
        if not os.path.isfile(safe):
            self._send_json(404, {"error": "not found"})
            return
        ext = os.path.splitext(safe)[1].lower()
        ct = {
            ".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8",
            ".js": "application/javascript", ".css": "text/css",
            ".png": "image/png", ".jpg": "image/jpeg", ".gif": "image/gif",
            ".svg": "image/svg+xml", ".webp": "image/webp", ".ico": "image/x-icon",
            ".xml": "application/xml", ".txt": "text/plain",
        }.get(ext, "application/octet-stream")
        try:
            with open(safe, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/api/status":
            self._send_json(200, {
                "sources": scan_api.source_status(),
                "running": _update_running["active"],
            })
            return
        if path == "/api/pending":
            # Return pending articles from index.json
            idx_path = os.path.join(ROOT, "data", "index.json")
            try:
                with open(idx_path, encoding="utf-8") as f:
                    idx = json.load(f)
                self._send_json(200, {"pending": idx.get("pending", [])})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return
        # Static file serving
        if path == "/" or path == "":
            self._serve_file("index.html")
            return
        # Strip leading slash
        self._serve_file(path.lstrip("/"))

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/review":
            self._handle_review()
            return
        if parsed.path != "/api/update":
            self._send_json(404, {"error": "not found"})
            return

        # Parse body
        length = int(self.headers.get("Content-Length", 0))
        try:
            raw = self.rfile.read(length) if length > 0 else b"{}"
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._send_json(400, {"error": "invalid JSON body"})
            return

        sources = body.get("sources", [])
        do_translate = body.get("translate", True)
        valid = [s for s in sources if s in scan_api.SOURCES]
        if not valid:
            self._send_json(400, {"error": "no valid sources", "valid": scan_api.SOURCES})
            return

        if not _update_lock.acquire(blocking=False):
            self._send_json(409, {"error": "update already in progress"})
            return

        _update_running["active"] = True

        # SSE streaming response
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True  # signal close after handler returns

        msg_q = queue.Queue()

        def progress_cb(d):
            msg_q.put(d)

        def worker():
            try:
                scan_api.run_update(valid, progress=progress_cb, do_translate=do_translate)
            except Exception as e:
                msg_q.put({"phase": "fatal", "msg": f"异常: {e}"})
            finally:
                msg_q.put(None)  # sentinel
                _update_running["active"] = False
                _update_lock.release()

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        # Stream SSE messages
        try:
            while True:
                try:
                    msg = msg_q.get(timeout=1.0)
                except queue.Empty:
                    # Send keepalive comment
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue
                if msg is None:
                    break
                data = json.dumps(msg, ensure_ascii=False)
                self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(description="Palantir blog archive dev server")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    server = ThreadedHTTPServer((args.host, args.port), Handler)
    print(f"Server running at http://localhost:{args.port}")
    print(f"  Static files:  / (index.html)")
    print(f"  API status:    /api/status")
    print(f"  API update:    POST /api/update  (SSE stream)")
    print(f"Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
