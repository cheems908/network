#!/usr/bin/env python3
"""A plain-HTTP forward proxy implemented with TCP sockets."""

from __future__ import annotations

import argparse
from collections import OrderedDict
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import re
import socket
from time import monotonic, time
from urllib.parse import urlsplit


MAX_HEADER_BYTES = 16 * 1024
READ_CHUNK = 16 * 1024
MAX_RESPONSE_HEADERS = 64 * 1024
CACHE_MAX_ENTRIES = 16
CACHE_MAX_RESPONSE = 256 * 1024
CACHE_MAX_AGE = 60
CACHE_BYPASS_HEADERS = {
    "authorization", "proxy-authorization", "cookie", "range", "cache-control", "pragma",
    "if-match", "if-none-match", "if-modified-since", "if-unmodified-since", "if-range",
}


@dataclass
class CachedResponse:
    header_lines: list[bytes]
    body: bytes
    age_at_store: float
    stored_at: float
    expires_at: float

    def send(self, client: socket.socket, now: float) -> None:
        age = int(self.age_at_store + now - self.stored_at)
        headers = b"\r\n".join(self.header_lines + [f"Age: {age}".encode("ascii")])
        client.sendall(headers + b"\r\n\r\n" + self.body)


CacheKey = tuple[str, int, str]
ResponseCache = OrderedDict[CacheKey, CachedResponse]


class ProxyError(Exception):
    def __init__(self, status: int, reason: str, detail: str):
        super().__init__(detail)
        self.status = status
        self.reason = reason
        self.detail = detail


def read_headers(connection: socket.socket) -> bytes:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = connection.recv(4096)
        if not chunk:
            raise ProxyError(400, "Bad Request", "connection closed during headers")
        data.extend(chunk)
        if len(data) > MAX_HEADER_BYTES:
            raise ProxyError(431, "Request Header Fields Too Large", "headers too large")
    return bytes(data).partition(b"\r\n\r\n")[0]


def parse_client_request(header_block: bytes) -> tuple[str, str, dict[str, str]]:
    try:
        lines = header_block.decode("iso-8859-1").split("\r\n")
    except UnicodeDecodeError as exc:
        raise ProxyError(400, "Bad Request", "invalid header bytes") from exc
    parts = lines[0].split()
    if len(parts) != 3:
        raise ProxyError(400, "Bad Request", "malformed request line")
    method, target, version = parts
    if method == "CONNECT":
        raise ProxyError(405, "Method Not Allowed", "CONNECT is not supported")
    if method not in ("GET", "HEAD"):
        raise ProxyError(405, "Method Not Allowed", "only GET and HEAD are supported")
    if version != "HTTP/1.1":
        raise ProxyError(400, "Bad Request", "only HTTP/1.1 is supported")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            raise ProxyError(400, "Bad Request", "malformed request header")
        name, value = line.split(":", 1)
        name = name.strip().lower()
        if not name:
            raise ProxyError(400, "Bad Request", "empty header name")
        headers[name] = value.strip()
    return method, target, headers


def origin_details(target: str) -> tuple[str, int, str, str]:
    try:
        parsed = urlsplit(target)
        port = parsed.port
    except ValueError as exc:
        raise ProxyError(400, "Bad Request", f"invalid URL: {exc}") from exc
    if parsed.scheme.lower() != "http":
        raise ProxyError(400, "Bad Request", "an absolute http:// URL is required")
    if not parsed.hostname:
        raise ProxyError(400, "Bad Request", "URL has no hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ProxyError(400, "Bad Request", "userinfo in URLs is not supported")
    if parsed.fragment:
        raise ProxyError(400, "Bad Request", "URL fragments are not valid here")
    if any(ord(char) < 0x21 for char in target):
        raise ProxyError(400, "Bad Request", "URL contains a control character")

    host = parsed.hostname
    port = port or 80
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    display_host = f"[{host}]" if ":" in host else host
    host_header = display_host if port == 80 else f"{display_host}:{port}"
    return host, port, path, host_header


def build_origin_request(path: str, host_header: str, method: str = "GET") -> bytes:
    lines = [
        f"{method} {path} HTTP/1.1",
        f"Host: {host_header}",
        "User-Agent: CNSCC231-SocketProxy/1.0",
        "Accept: */*",
        "Connection: close",
        "",
        "",
    ]
    return "\r\n".join(lines).encode("iso-8859-1")


def make_error(status: int, reason: str, detail: str, *, head_only: bool = False) -> bytes:
    body = f"{status} {reason}\n{detail}\n".encode("utf-8")
    allow = "Allow: GET, HEAD\r\n" if status == 405 else ""
    headers = (
        f"HTTP/1.1 {status} {reason}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"{allow}"
        "Connection: close\r\n\r\n"
    ).encode("iso-8859-1")
    return headers if head_only else headers + body


def content_length_from_response(header_bytes: bytes) -> int | None:
    try:
        lines = header_bytes.decode("iso-8859-1").split("\r\n")[1:]
        values = [
            value.strip()
            for name, value in (line.split(":", 1) for line in lines if ":" in line)
            if name.strip().lower() == "content-length"
        ]
        if len(values) == 1 and values[0].isdigit():
            return int(values[0])
    except (UnicodeDecodeError, ValueError):
        pass
    return None


def relay_origin_response(
    origin: socket.socket, client: socket.socket, first_chunk: bytes, *, capture: bool = False
) -> tuple[int, int | None, int, bytearray | None]:
    """Stream the response, retaining a copy only while it fits a cache entry."""
    total = 0
    response_prefix = bytearray()
    headers_complete = False
    expected_length: int | None = None
    body_bytes = 0
    captured = bytearray() if capture else None
    chunk = first_chunk
    while chunk:
        client.sendall(chunk)
        total += len(chunk)
        if captured is not None:
            if total <= CACHE_MAX_RESPONSE:
                captured.extend(chunk)
            else:
                captured = None
        if not headers_complete:
            response_prefix.extend(chunk)
            marker = response_prefix.find(b"\r\n\r\n")
            if marker != -1:
                headers_complete = True
                expected_length = content_length_from_response(
                    bytes(response_prefix[:marker])
                )
                body_bytes = len(response_prefix) - marker - 4
                response_prefix.clear()
            elif len(response_prefix) > MAX_RESPONSE_HEADERS:
                headers_complete = True
        else:
            body_bytes += len(chunk)
        chunk = origin.recv(READ_CHUNK)
    return total, expected_length, body_bytes, captured


def read_head_response(origin: socket.socket) -> bytes:
    data = bytearray()
    while True:
        chunk = origin.recv(READ_CHUNK)
        if not chunk:
            raise ProxyError(502, "Bad Gateway", "incomplete origin response headers")
        data.extend(chunk)
        marker = data.find(b"\r\n\r\n")
        if marker != -1 and marker <= MAX_RESPONSE_HEADERS:
            status = data.split(b"\r\n", 1)[0]
            if not re.fullmatch(rb"HTTP/1\.[01] [2-5][0-9]{2}(?: .*)?", status):
                raise ProxyError(502, "Bad Gateway", "expected a final HTTP response")
            return bytes(data[:marker + 4])
        if len(data) > MAX_RESPONSE_HEADERS:
            raise ProxyError(502, "Bad Gateway", "origin response headers too large")


def cacheable_response(response: bytearray, requested_at: float) -> CachedResponse | None:
    header_block, separator, body = response.partition(b"\r\n\r\n")
    if not separator or len(header_block) > MAX_RESPONSE_HEADERS:
        return None
    status_line, *fields = bytes(header_block).split(b"\r\n")
    if not re.fullmatch(rb"HTTP/1\.[01] 200(?: .*)?", status_line):
        return None

    headers = {}
    saved_lines = [status_line]
    for field in fields:
        name, colon, value = field.partition(b":")
        name = name.lower()
        if not colon or not re.fullmatch(rb"[a-z0-9!#$%&'*+.^_`|~-]+", name) or name in headers:
            return None
        headers[name] = value.strip()
        if name != b"age":
            saved_lines.append(field)

    unsupported = {
        b"vary", b"set-cookie", b"transfer-encoding", b"content-range", b"trailer",
        b"upgrade", b"pragma",
    }
    if unsupported.intersection(headers):
        return None
    if headers.get(b"connection", b"close").lower() != b"close":
        return None
    content_length = content_length_from_response(bytes(header_block))
    if content_length != len(body):
        return None
    cache_control = headers.get(b"cache-control", b"").lower()
    directives = [item.strip() for item in cache_control.split(b",")]
    if len(directives) != 2 or b"public" not in directives:
        return None
    directives.remove(b"public")
    max_age = re.fullmatch(rb"max-age=([0-9]{1,10})", directives[0])
    age_header = headers.get(b"age", b"0")
    if not max_age or not re.fullmatch(rb"[0-9]{1,10}", age_header):
        return None
    try:
        date = parsedate_to_datetime(headers.get(b"date", b"").decode("ascii"))
        if date.tzinfo is None:
            return None
        apparent_age = time() - date.timestamp()
    except (ValueError, OverflowError, OSError):
        return None
    now = monotonic()
    age = max(apparent_age, int(age_header) + now - requested_at)
    lifetime = min(int(max_age[1]), CACHE_MAX_AGE) - age
    if lifetime <= 0:
        return None
    return CachedResponse(saved_lines, bytes(body), age, now, now + lifetime)


def handle_client(
    client: socket.socket, client_address, client_timeout: float, origin_timeout: float,
    cache: ResponseCache | None = None,
) -> None:
    client.settimeout(client_timeout)
    response_started = False
    origin = None
    target = "<unparsed>"
    method = ""
    try:
        header_block = read_headers(client)
        method, target, headers = parse_client_request(header_block)
        host, port, path, host_header = origin_details(target)
        cache_key = (host, port, path)
        use_cache = (
            cache is not None and method == "GET"
            and not CACHE_BYPASS_HEADERS.intersection(headers)
        )
        if use_cache:
            entry = cache.get(cache_key)
            now = monotonic()
            if entry is not None and now < entry.expires_at:
                cache.move_to_end(cache_key)
                response_started = True
                entry.send(client, now)
                print(f"HIT {target}")
                return
            cache.pop(cache_key, None)
            print(f"MISS {target}")
        requested_at = monotonic()
        try:
            origin = socket.create_connection((host, port), timeout=origin_timeout)
            origin.settimeout(origin_timeout)
            origin.sendall(build_origin_request(path, host_header, method))
        except socket.timeout as exc:
            raise ProxyError(504, "Gateway Timeout", "origin connection timed out") from exc
        except OSError as exc:
            raise ProxyError(502, "Bad Gateway", f"origin connection failed: {exc}") from exc

        try:
            if method == "HEAD":
                head = read_head_response(origin)
                response_started = True
                client.sendall(head)
                print(f"{client_address}: HEAD {target} -> relayed {len(head)} header bytes")
                return
            first_chunk = origin.recv(READ_CHUNK)
            if not first_chunk:
                raise ProxyError(502, "Bad Gateway", "origin closed without a response")
            response_started = True
            total, expected_length, body_bytes, captured = relay_origin_response(
                origin, client, first_chunk, capture=use_cache
            )
        except socket.timeout as exc:
            raise ProxyError(504, "Gateway Timeout", "origin response timed out") from exc
        except OSError as exc:
            raise ProxyError(502, "Bad Gateway", f"origin transfer failed: {exc}") from exc
        if expected_length is not None and body_bytes != expected_length:
            print(
                f"{client_address}: upstream body ended early or was oversized "
                f"({body_bytes}/{expected_length} bytes); client connection closed"
            )
        else:
            if cache is not None and captured is not None:
                entry = cacheable_response(captured, requested_at)
                if entry is not None:
                    cache[cache_key] = entry
                    if len(cache) > CACHE_MAX_ENTRIES:
                        cache.popitem(last=False)
            print(
                f"{client_address[0]}:{client_address[1]} {target} "
                f"-> relayed {total} bytes"
            )
    except socket.timeout:
        if not response_started:
            try:
                client.sendall(make_error(408, "Request Timeout", "client request timed out"))
            except OSError:
                pass
    except ProxyError as error:
        if not response_started:
            try:
                client.sendall(make_error(
                    error.status, error.reason, error.detail, head_only=method == "HEAD"
                ))
            except OSError:
                pass
        print(f"{client_address}: {target} -> {error.status} ({error.detail})")
    except OSError as exc:
        print(f"{client_address}: client connection error: {exc}")
    finally:
        if origin is not None:
            origin.close()


def start_proxy(
    address: str, port: int, client_timeout: float, origin_timeout: float,
    enable_cache: bool = False,
) -> None:
    cache = OrderedDict() if enable_cache else None
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((address, port))
        server.listen()
        shown_address = address or "0.0.0.0"
        print(f"Proxy listening on http://{shown_address}:{port}")
        try:
            while True:
                client, client_address = server.accept()
                with client:
                    handle_client(client, client_address, client_timeout, origin_timeout, cache)
        except KeyboardInterrupt:
            print("\nProxy stopped")


def valid_port(value: str) -> int:
    port = int(value)
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1024 and 65535")
    return port


def positive_float(value: str) -> float:
    result = float(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plain HTTP forward proxy")
    parser.add_argument("--address", default="127.0.0.1")
    parser.add_argument("--port", type=valid_port, default=8080)
    parser.add_argument("--client-timeout", type=positive_float, default=5.0)
    parser.add_argument("--origin-timeout", type=positive_float, default=5.0)
    parser.add_argument("--cache", action="store_true", help="enable the bounded in-memory GET cache")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        start_proxy(
            args.address, args.port, args.client_timeout, args.origin_timeout, args.cache
        )
    except OSError as exc:
        print(f"proxy: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
