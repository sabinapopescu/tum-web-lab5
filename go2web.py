#!/usr/bin/env python3

import socket
import ssl
import sys
import os
import re
import json
import hashlib
import time
import argparse
from html.parser import HTMLParser
from urllib.parse import urlparse, quote_plus, unquote, parse_qs

# ─── Cache config ────────────────────────────────────────────────────────────
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".go2web_cache")
CACHE_TTL = 3600  # 1 hour

# ─── HTML → plain text ───────────────────────────────────────────────────────
class TextExtractor(HTMLParser):
    SKIP_TAGS = {"script", "style", "noscript", "head", "meta", "link", "svg"}

    def __init__(self):
        super().__init__()
        self._skip = 0
        self.chunks = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip += 1
        if tag == "br":
            self.chunks.append("\n")
        if tag in ("p", "div", "h1", "h2", "h3", "h4", "li", "tr", "article", "section"):
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS:
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data):
        if self._skip == 0:
            text = data.strip()
            if text:
                self.chunks.append(text + " ")

    def get_text(self):
        raw = "".join(self.chunks)
        lines = [l.strip() for l in raw.splitlines()]
        lines = [l for l in lines if l]
        out, prev_blank = [], False
        for l in lines:
            if not l:
                if not prev_blank:
                    out.append("")
                prev_blank = True
            else:
                out.append(l)
                prev_blank = False
        return "\n".join(out)


def html_to_text(html):
    p = TextExtractor()
    try:
        p.feed(html)
    except Exception:
        pass
    text = p.get_text()
    if not text.strip():
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"[ \t]+", " ", text)
        text = "\n".join(l.strip() for l in text.splitlines() if l.strip())
    return text


# ─── Cache helpers ────────────────────────────────────────────────────────────
def cache_key(url):
    return hashlib.md5(url.encode()).hexdigest()

def cache_get(url):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, cache_key(url) + ".json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            entry = json.load(f)
        if time.time() - entry["ts"] > CACHE_TTL:
            os.remove(path)
            return None
        return entry["body"]
    except Exception:
        return None

def cache_set(url, body):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, cache_key(url) + ".json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "body": body}, f, ensure_ascii=False)
    except Exception:
        pass

def cache_clear(url):
    path = os.path.join(CACHE_DIR, cache_key(url) + ".json")
    if os.path.exists(path):
        os.remove(path)


# ─── Raw TCP/TLS request ─────────────────────────────────────────────────────
def make_request(url, max_redirects=8):
    for _ in range(max_redirects):
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        port = parsed.port or (443 if scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        try:
            raw = _tcp_fetch(host, port, path, scheme)
        except Exception as e:
            print(f"Connection error: {e}", file=sys.stderr)
            return None, {}, ""

        status, headers, body = _parse_response(raw)

        if status in (301, 302, 303, 307, 308):
            location = headers.get("location", "")
            if not location:
                break
            if location.startswith("/"):
                location = f"{scheme}://{host}{location}"
            elif not location.startswith("http"):
                location = f"{scheme}://{host}/{location}"
            url = location
            continue

        return status, headers, body

    return None, {}, ""


def _tcp_fetch(host, port, path, scheme):
    sock = socket.create_connection((host, port), timeout=15)
    if scheme == "https":
        ctx = ssl.create_default_context()
        sock = ctx.wrap_socket(sock, server_hostname=host)

    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"User-Agent: Mozilla/5.0 (compatible; go2web/1.0)\r\n"
        f"Accept: text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8\r\n"
        f"Accept-Language: en-US,en;q=0.5\r\n"
        f"Accept-Encoding: identity\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    )
    sock.sendall(request.encode())

    raw = b""
    while True:
        chunk = sock.recv(8192)
        if not chunk:
            break
        raw += chunk
    sock.close()
    return raw


def _parse_response(raw):
    sep = b"\r\n\r\n"
    idx = raw.find(sep)
    if idx == -1:
        return 0, {}, raw.decode("utf-8", errors="replace")

    header_bytes = raw[:idx]
    body_bytes = raw[idx + 4:]

    header_lines = header_bytes.decode("utf-8", errors="replace").splitlines()
    status_line = header_lines[0] if header_lines else ""
    try:
        status = int(status_line.split()[1])
    except (IndexError, ValueError):
        status = 0

    headers = {}
    for line in header_lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()

    if headers.get("transfer-encoding", "").lower() == "chunked":
        body_bytes = _decode_chunked(body_bytes)

    charset = "utf-8"
    ct = headers.get("content-type", "")
    if "charset=" in ct:
        charset = ct.split("charset=")[-1].split(";")[0].strip()

    body = body_bytes.decode(charset, errors="replace")
    return status, headers, body


def _decode_chunked(data):
    result = b""
    while data:
        crlf = data.find(b"\r\n")
        if crlf == -1:
            break
        try:
            size = int(data[:crlf], 16)
        except ValueError:
            break
        if size == 0:
            break
        start = crlf + 2
        result += data[start:start + size]
        data = data[start + size + 2:]
    return result


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


def _fallback_parse(html):
    results = []
    for m in re.finditer(r'href="(https?://(?!.*duckduckgo\.com)[^"]{10,})"[^>]*>\s*([^<]{5,120})', html):
        url, title = m.group(1).strip(), m.group(2).strip()
        if not any(r["url"] == url for r in results):
            results.append({"title": title, "url": url})
    return results


def search_ddg(term):
    query = quote_plus(term)
    url = f"https://html.duckduckgo.com/html/?q={query}"

    from_cache = False
    cached = cache_get(url)
    if cached:
        html = cached
        from_cache = True
    else:
        status, headers, html = make_request(url)
        if not html.strip():
            print("Empty response from DuckDuckGo.")
            return []
        cache_set(url, html)

    if from_cache:
        print("(cached)\n")

    parser = DDGParser()
    parser.feed(html)
    results = parser.results[:10]

    if not results:
        results = _fallback_parse(html)[:10]

    if not results:
        print("No results found.")
        print(f"Tip: delete cache folder and retry: {CACHE_DIR}")
        return []

    for i, r in enumerate(results, 1):
        print(f"{i:2}. {r['title']}")
        print(f"    {r['url']}\n")

    return results


# ─── Fetch + display URL ──────────────────────────────────────────────────────
def fetch_url(url):
    if not url.startswith("http"):
        url = "https://" + url

    cached = cache_get(url)
    if cached:
        print("(cached)\n")
        print(cached)
        return

    status, headers, body = make_request(url)

    if status is None:
        print("Error: request failed (too many redirects or connection error).")
        sys.exit(1)

    ct = headers.get("content-type", "")
    if "json" in ct:
        try:
            output = json.dumps(json.loads(body), indent=2, ensure_ascii=False)
        except Exception:
            output = body
    else:
        output = html_to_text(body)

    if not output.strip():
        print(f"[Empty response — HTTP {status}]")
        return

    cache_set(url, output)
    print(output)


# ─── CLI ──────────────────────────────────────────────────────────────────────
HELP = """go2web — HTTP over raw TCP sockets

Usage:
  go2web -u <URL>           Make an HTTP request and print human-readable output
  go2web -s <search term>   Search DuckDuckGo and print top 10 results
  go2web -h                 Show this help
  go2web -u <URL> --clear-cache   Force fresh fetch (ignore cache)

Cache:
  Responses cached 1 hour in ~/.go2web_cache/

Examples:
  go2web -u https://example.com
  go2web -u http://info.cern.ch
  go2web -s python sockets tutorial
"""

def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-u", metavar="URL")
    parser.add_argument("-s", metavar="TERM", nargs="+")
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("--clear-cache", action="store_true")

    args = parser.parse_args()

    if args.help or (not args.u and not args.s):
        print(HELP)
        return

    if args.u:
        if args.clear_cache:
            cache_clear(args.u)
        fetch_url(args.u)

    if args.s:
        term = " ".join(args.s)
        search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(term)}"
        if args.clear_cache:
            cache_clear(search_url)
        results = search_ddg(term)

        if results:
            print("Enter result number to open, or press Enter to quit: ", end="", flush=True)
            try:
                choice = input().strip()
                if choice.isdigit():
                    idx = int(choice) - 1
                    if 0 <= idx < len(results):
                        print(f"\n─── {results[idx]['url']} ───\n")
                        fetch_url(results[idx]["url"])
            except (EOFError, KeyboardInterrupt):
                pass


if __name__ == "__main__":
    main()