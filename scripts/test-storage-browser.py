#!/usr/bin/env python3
"""Exercise presigned storage using actual browser fetch, without application credentials."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
import threading

from playwright.sync_api import sync_playwright


class OriginHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<!doctype html><title>Storage protocol check</title>")

    def log_message(self, *_):
        pass


def main():
    capabilities = json.load(sys.stdin)
    # A fixed exact origin also detects accidental wildcard/mismatched CORS configuration.
    with ThreadingHTTPServer(("127.0.0.1", 8765), OriginHandler) as origin:
        thread = threading.Thread(target=origin.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page()
                    page.set_default_timeout(30000)
                    page.goto("http://127.0.0.1:8765")
                    result = page.evaluate("""async ({upload, download}) => {
                        const bytes = new TextEncoder().encode('hello');
                        // Content-Length is deliberately absent: the browser supplies it.
                        const put = await fetch(upload.url, {method:'PUT', headers:upload.headers,
                            body:new Blob([bytes]), signal:AbortSignal.timeout(20000)});
                        if (!put.ok || !put.headers.get('etag')) throw new Error('browser PUT/ETag failed');
                        const replay = await fetch(upload.url, {method:'PUT', headers:upload.headers,
                            body:new Blob([bytes]), signal:AbortSignal.timeout(20000)});
                        if (replay.status !== 412) throw new Error('browser conditional replay failed');
                        const get = await fetch(download, {headers:{Range:'bytes=1-3'},
                            signal:AbortSignal.timeout(20000)});
                        if (get.status !== 206 || get.headers.get('content-range') !== 'bytes 1-3/5'
                            || !get.headers.get('content-disposition') || await get.text() !== 'ell')
                            throw new Error('browser GET/Range/CORS exposure failed');
                        return {put:put.status,replay:replay.status,get:get.status};
                    }""", capabilities)
                    assert result["replay"] == 412 and result["get"] == 206
                    # An unrelated Origin must not receive access even with a valid URL.
                    page.goto("http://localhost:8765")
                    denied = page.evaluate("""async ({download}) => {
                        try { await fetch(download, {signal:AbortSignal.timeout(10000)}); return false; }
                        catch { return true; }
                    }""", capabilities)
                    assert denied, "storage CORS accepted an unconfigured origin"
                    print("Browser PUT, conditional replay, GET Range, ETag exposure and exact-origin CORS passed.")
                finally:
                    browser.close()
        finally:
            origin.shutdown()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
