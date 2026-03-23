#!/usr/bin/env python3

import socket
import ssl
import sys
import argparse
from html.parser import HTMLParser
from urllib.parse import urlparse, quote_plus

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
        if tag in ("p", "br", "h1", "h2", "h3", "li", "div"):
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
    try:
        p.feed(html)
    except Exception:
        pass
    return p.get_text()


# ─── Raw TCP/TLS request ─────────────────────────────────────────────────────
def make_request(url):
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname
    port = parsed.port or (443 if scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query

    sock = socket.create_connection((host, port), timeout=10)
    if scheme == "https":
        ctx = ssl.create_default_context()
        sock = ctx.wrap_socket(sock, server_hostname=host)

    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"User-Agent: go2web/1.0\r\n"
        f"Accept: text/html\r\n"
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

    idx = raw.find(b"\r\n\r\n")
    if idx == -1:
        return 200, {}, raw.decode("utf-8", errors="replace")

    header_lines = raw[:idx].decode("utf-8", errors="replace").splitlines()
    status = int(header_lines[0].split()[1]) if header_lines else 200
    body = raw[idx + 4:].decode("utf-8", errors="replace")
    return status, {}, body


# ─── DuckDuckGo search ────────────────────────────────────────────────────────
class DDGParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self._active = False
        self._url = None
        self._title = ""

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        attrs = dict(attrs)
        cls = attrs.get("class", "")
        if "result__a" not in cls:
            return
        href = attrs.get("href", "")
        from urllib.parse import parse_qs, unquote
        if "uddg=" in href:
            qs = parse_qs(urlparse(href).query)
            real = qs.get("uddg", [None])[0]
            if real:
                href = unquote(real)
        if href.startswith("http") and "duckduckgo.com" not in href:
            self._url = href
            self._active = True
            self._title = ""

    def handle_data(self, data):
        if self._active:
            self._title += data

    def handle_endtag(self, tag):
        if tag == "a" and self._active:
            self._active = False
            title = self._title.strip()
            if title and self._url:
                if not any(r["url"] == self._url for r in self.results):
                    self.results.append({"title": title, "url": self._url})
            self._url = None
            self._title = ""


def search_ddg(term):
    query = quote_plus(term)
    url = f"https://html.duckduckgo.com/html/?q={query}"
    status, _, html = make_request(url)

    parser = DDGParser()
    parser.feed(html)
    results = parser.results[:10]

    if not results:
        print("No results found.")
        return

    for i, r in enumerate(results, 1):
        print(f"{i:2}. {r['title']}")
        print(f"    {r['url']}\n")


def fetch_url(url):
    if not url.startswith("http"):
        url = "https://" + url
    status, _, body = make_request(url)
    print(html_to_text(body))


# ─── CLI ─────────────────────────────────────────────────────────────────────
HELP = """go2web — HTTP over raw TCP sockets

Usage:
  go2web -u <URL>          Make an HTTP request and print human-readable output
  go2web -s <search term>  Search DuckDuckGo and print top 10 results
  go2web -h                Show this help

Examples:
  go2web -u https://example.com
  go2web -s python sockets tutorial
"""

def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-u", metavar="URL")
    parser.add_argument("-s", metavar="TERM", nargs="+")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args()

    if args.help or (not args.u and not args.s):
        print(HELP)
        return

    if args.u:
        fetch_url(args.u)

    if args.s:
        search_ddg(" ".join(args.s))


if __name__ == "__main__":
    main()