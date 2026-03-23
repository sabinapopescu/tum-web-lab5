#!/usr/bin/env python3

import socket
import ssl
import sys
import argparse
from html.parser import HTMLParser
from urllib.parse import urlparse

# ─── HTML → plain text ───────────────────────────────────────────────────────
class TextExtractor(HTMLParser):
    SKIP_TAGS = {"script", "style", "noscript", "head"}

    def __init__(self):
        super().__init__()
        self._skip = 0
        self.chunks = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip += 1
        if tag in ("p", "br", "h1", "h2", "h3", "li"):
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS:
            self._skip -= 1

    def handle_data(self, data):
        if self._skip == 0:
            text = data.strip()
            if text:
                self.chunks.append(text + " ")

    def get_text(self):
        raw = "".join(self.chunks)
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        return "\n".join(lines)


def html_to_text(html):
    p = TextExtractor()
    p.feed(html)
    return p.get_text()


# ─── Raw TCP request ─────────────────────────────────────────────────────────
def make_request(url):
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname
    port = parsed.port or (443 if scheme == "https" else 80)
    path = parsed.path or "/"

    sock = socket.create_connection((host, port), timeout=10)

    if scheme == "https":
        ctx = ssl.create_default_context()
        sock = ctx.wrap_socket(sock, server_hostname=host)

    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"User-Agent: go2web/1.0\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    )
    sock.sendall(request.encode())

    raw = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        raw += chunk
    sock.close()

    # split headers and body
    idx = raw.find(b"\r\n\r\n")
    body = raw[idx + 4:].decode("utf-8", errors="replace")
    return body


def fetch_url(url):
    if not url.startswith("http"):
        url = "https://" + url
    body = make_request(url)
    print(html_to_text(body))


# ─── CLI ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-u", metavar="URL")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args()

    if args.help or not args.u:
        print("Usage:\n  go2web -u <URL>\n  go2web -h")
        return

    if args.u:
        fetch_url(args.u)


if __name__ == "__main__":
    main()