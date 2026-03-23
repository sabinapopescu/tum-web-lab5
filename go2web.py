#!/usr/bin/env python3

import socket
import ssl
import sys
import argparse
from html.parser import HTMLParser
from urllib.parse import urlparse, quote_plus, parse_qs, unquote

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
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        return "\n".join(lines)


def html_to_text(html):
    p = TextExtractor()
    try:
        p.feed(html)
    except Exception:
        pass
    return p.get_text()


# ─── Raw TCP/TLS request with redirect support ────────────────────────────────
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
        f"Accept: text/html,application/json;q=0.9,*/*;q=0.8\r\n"
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
        if "result__a" not in attrs.get("class", ""):
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


def search_ddg(term):
    query = quote_plus(term)
    url = f"https://html.duckduckgo.com/html/?q={query}"
    status, headers, html = make_request(url)

    parser = DDGParser()
    parser.feed(html)
    results = parser.results[:10]

    if not results:
        print("No results found.")
        return []

    for i, r in enumerate(results, 1):
        print(f"{i:2}. {r['title']}")
        print(f"    {r['url']}\n")

    return results


def fetch_url(url):
    if not url.startswith("http"):
        url = "https://" + url

    status, headers, body = make_request(url)
    if status is None:
        print("Error: request failed.")
        sys.exit(1)

    import json
    ct = headers.get("content-type", "")
    if "json" in ct:
        try:
            output = json.dumps(json.loads(body), indent=2)
        except Exception:
            output = body
    else:
        output = html_to_text(body)

    print(output)


# ─── CLI ─────────────────────────────────────────────────────────────────────
HELP = """go2web — HTTP over raw TCP sockets

Usage:
  go2web -u <URL>          Make an HTTP request and print human-readable output
  go2web -s <search term>  Search DuckDuckGo and print top 10 results
  go2web -h                Show this help

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
    args = parser.parse_args()

    if args.help or (not args.u and not args.s):
        print(HELP)
        return

    if args.u:
        fetch_url(args.u)

    if args.s:
        term = " ".join(args.s)
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