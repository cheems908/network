#!/usr/bin/env python3
"""Download a file over plain HTTP using a TCP socket."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import socket
import sys
from tempfile import NamedTemporaryFile
from urllib.parse import quote, urlsplit


MAX_HEADER_BYTES = 64 * 1024
READ_CHUNK = 16 * 1024


def parse_url(url: str) -> tuple[str, int, str, str]:
    if any(ord(char) < 0x21 or ord(char) == 0x7f for char in url):
        raise ValueError("URL contains whitespace or a control character")
    parsed = urlsplit(url)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username is not None:
        raise ValueError("expected an http:// URL without credentials")
    if parsed.fragment:
        raise ValueError("URL fragments are not supported")
    host = parsed.hostname.encode("idna").decode("ascii")
    port = parsed.port if parsed.port is not None else 80
    if port == 0:
        raise ValueError("port must be greater than zero")
    authority = f"[{host}]" if ":" in host else host
    if port != 80:
        authority += f":{port}"
    path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=")
    if parsed.query:
        path += "?" + quote(parsed.query, safe="/?%:@!$&'()*+,;=")
    return host, port, authority, path


def read_response(stream) -> tuple[str, int, list[str], dict[str, list[str]]]:
    remaining = MAX_HEADER_BYTES

    def read_line() -> str:
        nonlocal remaining
        raw = stream.readline(remaining + 1)
        remaining -= len(raw)
        if remaining < 0:
            raise ValueError("response headers are too large")
        if not raw.endswith(b"\r\n"):
            raise ValueError("incomplete response headers")
        return raw[:-2].decode("iso-8859-1")

    status_line = read_line()
    match = re.fullmatch(r"HTTP/1\.[01] ([1-5][0-9]{2})(?: .*)?", status_line)
    if not match:
        raise ValueError("invalid HTTP response status line")
    status = int(match[1])
    lines = []
    headers: dict[str, list[str]] = {}
    while line := read_line():
        name, separator, value = line.partition(":")
        if not separator or not name:
            raise ValueError("malformed response header")
        lines.append(line)
        headers.setdefault(name.lower(), []).append(value.strip())
    return status_line, status, lines, headers


def save_body(stream, output: Path, length: int | None) -> None:
    temporary = None
    try:
        with NamedTemporaryFile(dir=output.parent, delete=False) as destination:
            temporary = Path(destination.name)
            while length is None or length > 0:
                chunk = stream.read(READ_CHUNK if length is None else min(length, READ_CHUNK))
                if not chunk:
                    if length is not None:
                        raise ValueError("response ended before Content-Length bytes arrived")
                    break
                destination.write(chunk)
                if length is not None:
                    length -= len(chunk)
        temporary.replace(output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def download(url: str, proxy: str | None, output: Path) -> int:
    host, port, authority, target = parse_url(url)
    if proxy is not None:
        host, port, _, proxy_path = parse_url(proxy)
        if proxy_path != "/":
            raise ValueError("--proxy must be an http:// host and port")
        target = f"http://{authority}{target}"
    request = (
        f"GET {target} HTTP/1.1\r\nHost: {authority}\r\n"
        "Accept: */*\r\nConnection: close\r\n\r\n"
    ).encode("ascii")

    with socket.create_connection((host, port), timeout=5) as connection:
        connection.sendall(request)
        with connection.makefile("rb") as stream:
            status_line, status, lines, headers = read_response(stream)
            print("\n".join([status_line, *lines, ""]))
            if status != 200:
                return 1
            if "transfer-encoding" in headers:
                raise ValueError("this client supports Content-Length and close-delimited bodies")
            length = None
            if "content-length" in headers:
                values = headers["content-length"]
                if len(values) != 1 or not re.fullmatch(r"[0-9]+", values[0]):
                    raise ValueError("invalid Content-Length")
                length = int(values[0])
            save_body(stream, output, length)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Download a file over a plain HTTP socket")
    parser.add_argument("url")
    parser.add_argument("--proxy", help="optional proxy URL, e.g. http://127.0.0.1:8080")
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        return download(args.url, args.proxy, args.output)
    except (OSError, ValueError) as exc:
        print(f"client: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
