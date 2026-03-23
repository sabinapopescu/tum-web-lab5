
# Lab 5 · Network Programming · FAF · Technical University of Moldova
> go2web — HTTP over TCP Sockets

A command-line tool that makes HTTP/HTTPS requests using **raw TCP sockets** — no HTTP libraries allowed. Built in Python using only `socket`, `ssl`, and `html.parser` from the standard library.



## Features

| Feature | Points |
|---|---|
| `-h`, `-u`, `-s` flags all working | +6 |
| HTTP redirect following (301, 302, 303, 307, 308) | +1 |
| Interactive: open search result by number | +1 |
| File-based HTTP cache with 1h TTL | +2 |
| Content negotiation — handles both HTML and JSON responses | +2 |

---

## Usage

```
go2web -u <URL>          Make an HTTP request and print human-readable output
go2web -s <search term>  Search DuckDuckGo and print top 10 results
go2web -h                Show this help
```


## How it works

### Raw TCP socket request

Instead of using `requests`, `urllib`, or any HTTP library, the program opens a raw TCP socket and writes the HTTP request as a plain string:

```
GET /path HTTP/1.1\r\n
Host: example.com\r\n
User-Agent: Mozilla/5.0 (compatible; go2web/1.0)\r\n
Accept: text/html,application/json;q=0.9,*/*;q=0.8\r\n
Accept-Encoding: identity\r\n
Connection: close\r\n
\r\n
```

For HTTPS, the socket is wrapped with Python's built-in `ssl` module.

### Response parsing

The raw bytes are split on `\r\n\r\n` to separate headers from body. Status code is parsed from the first header line. Chunked transfer encoding is decoded manually.

### HTML → plain text

A custom `HTMLParser` subclass skips `<script>`, `<style>`, `<svg>`, and `<head>` tags, inserts newlines at block elements, and collects text nodes — producing clean, human-readable output with no HTML tags.

### HTTP redirects

If the response status is 301, 302, 303, 307, or 308, the `Location` header is followed automatically. Relative redirect paths are resolved against the original host. Up to 8 redirects are followed before giving up.

### Content negotiation

The `Accept` header is sent with both `text/html` and `application/json`. If the response `Content-Type` contains `json`, the body is parsed and pretty-printed with `json.dumps(..., indent=2)`. Otherwise it goes through the HTML stripper.

### Cache

Responses are cached as JSON files in `~/.go2web_cache/`, keyed by an MD5 hash of the URL. Cache entries expire after 1 hour. Use `--clear-cache` to force a fresh request.

```
~/.go2web_cache/
  a1b2c3d4e5f6....json   ← { "ts": 1234567890, "body": "..." }
  ...
```

### DuckDuckGo search

The program hits `https://html.duckduckgo.com/html/?q=<term>` — DuckDuckGo's lightweight HTML-only endpoint (no JavaScript required). Result links are parsed by targeting `class="result__a"` anchors and unwrapping DDG's redirect URLs (`/l/?uddg=...`).

---

## Project structure

```
pWeb/
├── go2web.py     # main script
├── go2web.bat    # Windows executable wrapper
└── README.md
```
### Output

```bash
C:\Users\sabi2\tum-web-lab5>go2web -h   
go2web — HTTP over raw TCP sockets

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


C:\Users\sabi2\tum-web-lab5> go2web -u http://info.cern.ch
http://info.cern.ch
http://info.cern.ch - home of the first website
From here you can:
Browse the first website
Browse the first website using the line-mode browser simulator
Learn about the birth of the web
Learn about CERN, the physics laboratory where the web was born

C:\Users\sabi2\tum-web-lab5>go2web -s python sockets tutorial
 1. Socket Programming in Python (Guide) - Real Python
    https://realpython.com/python-sockets/

 2. Socket Programming HOWTO — Python 3.14.3 documentation
    https://docs.python.org/3/howto/sockets.html

 3. Socket Programming in Python - GeeksforGeeks
    https://www.geeksforgeeks.org/python/socket-programming-python/

 4. A Complete Guide to Socket Programming in Python - DataCamp
    https://www.datacamp.com/tutorial/a-complete-guide-to-socket-programming-in-python

 5. Python Socket: Technical Guide for Beginners and Experts
    https://www.pythoncentral.io/learn-python-socket/

 6. Python socket Module - W3Schools
    https://www.w3schools.com/python/ref_module_socket.asp

 7. Python Socket Programming: Server and Client Example Guide
    https://www.digitalocean.com/community/tutorials/python-socket-programming-server-client

 8. Python Socket Programming: A Comprehensive Guide
    https://coderivers.org/blog/python-socket-programming/

 9. Python - Socket Programming - Online Tutorials Library
    https://www.tutorialspoint.com/python/python_socket_programming.htm

10. Python Programming Tutorials
    https://pythonprogramming.net/sockets-tutorial-python-3/

Enter result number to open, or press Enter to quit: 3

─── https://www.geeksforgeeks.org/python/socket-programming-python/ ───

Courses
Tutorials
Interview Prep
.
.
.
@GeeksforGeeks, Sanchhaya Education Private Limited , All rights reserved........

C:\Users\sabi2\tum-web-lab5>go2web -s python sockets --clear-cache
 1. socket — Low-level networking interface — Python 3.14.3 documentation
    https://docs.python.org/3/library/socket.html

 2. Socket Programming in Python (Guide) - Real Python
    https://realpython.com/python-sockets/

 3. Socket Programming in Python - GeeksforGeeks
    https://www.geeksforgeeks.org/python/socket-programming-python/

 4. Python socket Module - W3Schools
    https://www.w3schools.com/python/ref_module_socket.asp

 5. A Complete Guide to Socket Programming in Python - DataCamp
    https://www.datacamp.com/tutorial/a-complete-guide-to-socket-programming-in-python

 6. Python Socket: Technical Guide for Beginners and Experts
    https://www.pythoncentral.io/learn-python-socket/

 7. Python Socket Programming: A Comprehensive Guide
    https://coderivers.org/blog/python-socket-programming/

 8. What is Socket Programming in Python? - freeCodeCamp.org
    https://www.freecodecamp.org/news/socket-programming-in-python/

 9. Socket Programming HOWTO — Python 3.14.3 documentation
    https://docs.python.org/3/howto/sockets.html

10. Python Network - Sockets Programming - Online Tutorials Library
    https://www.tutorialspoint.com/python_network_programming/python_sockets_programming.htm

Enter result number to open, or press Enter to quit:
```

---
---
### Examples

```bash
# Fetch a webpage (HTML stripped, plain text output)
go2web -u https://example.com

# Fetch a JSON API endpoint
go2web -u https://api.github.com/users/octocat

# Search DuckDuckGo and print top 10 results
go2web -s python tcp sockets

# Open a search result directly by number
go2web -s moldova software company
# → type "3" to open result #3 in the terminal

# Force fresh fetch, bypassing cache
go2web -u https://example.com --clear-cache
go2web -s python sockets --clear-cache
```

---

## Installation

### Requirements
- Python 3.6+
- No third-party packages needed

### Windows

```bat
# Clone or download the repo, then run from the project folder:
go2web -h
```

The `go2web.bat` wrapper calls the Python script automatically.

### Linux / macOS

```bash
chmod +x go2web.py
sudo cp go2web.py /usr/local/bin/go2web
go2web -h
```

---

## Limitations

- Sites that require JavaScript (SPAs) will return minimal content — only what's in the raw HTML
- Some sites block non-browser User-Agent strings (mitigated by using a browser-like UA)
- No support for HTTP/2 or compressed responses (`Accept-Encoding: identity` disables compression)