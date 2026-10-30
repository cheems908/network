#!/usr/bin/env python3
"""A plain-HTTP forward proxy implemented with TCP sockets."""

from __future__ import annotations

import argparse
import socket
from urllib.parse import urlsplit


MAX_HEADER_BYTES = 16 * 1024
READ_CHUNK = 16 * 1024


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
    if method != "GET":
        raise ProxyError(405, "Method Not Allowed", "only GET is supported")
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
    return target, version, headers


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


def build_origin_request(path: str, host_header: str) -> bytes:
    lines = [
        f"GET {path} HTTP/1.1",
        f"Host: {host_header}",
        "User-Agent: CNSCC231-SocketProxy/1.0",
        "Accept: */*",
        "Connection: close",
        "",
        "",
    ]
    return "\r\n".join(lines).encode("iso-8859-1")


def make_error(status: int, reason: str, detail: str) -> bytes:
    body = f"{status} {reason}\n{detail}\n".encode("utf-8")
    return (
        f"HTTP/1.1 {status} {reason}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("iso-8859-1") + body


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
    origin: socket.socket, client: socket.socket, first_chunk: bytes
) -> tuple[int, int | None, int]:
    """Relay bytes until EOF and return total, expected body size and body size."""
    total = 0
    response_prefix = bytearray()
    headers_complete = False
    expected_length: int | None = None
    body_bytes = 0
    chunk = first_chunk
    while chunk:
        client.sendall(chunk)
        total += len(chunk)
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
            elif len(response_prefix) > 64 * 1024:
                headers_complete = True
        else:
            body_bytes += len(chunk)
        chunk = origin.recv(READ_CHUNK)
    return total, expected_length, body_bytes


def handle_client(
    client: socket.socket, client_address, client_timeout: float, origin_timeout: float
) -> None:
    client.settimeout(client_timeout)
    response_started = False
    origin = None
    target = "<unparsed>"
    try:
        header_block = read_headers(client)
        target, _, _ = parse_client_request(header_block)
        host, port, path, host_header = origin_details(target)
        try:
            origin = socket.create_connection((host, port), timeout=origin_timeout)
            origin.settimeout(origin_timeout)
            origin.sendall(build_origin_request(path, host_header))
        except socket.timeout as exc:
            raise ProxyError(504, "Gateway Timeout", "origin connection timed out") from exc
        except OSError as exc:
            raise ProxyError(502, "Bad Gateway", f"origin connection failed: {exc}") from exc

        try:
            first_chunk = origin.recv(READ_CHUNK)
            if not first_chunk:
                raise ProxyError(502, "Bad Gateway", "origin closed without a response")
            response_started = True
            total, expected_length, body_bytes = relay_origin_response(
                origin, client, first_chunk
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
            print(
                f"{client_address[0]}:{client_address[1]} {target} "
                f"-> relayed {total} bytes"
            )
    except socket.timeout:
        error = ProxyError(408, "Request Timeout", "client request timed out")
        try:
            client.sendall(make_error(error.status, error.reason, error.detail))
        except OSError:
            pass
    except ProxyError as error:
        if not response_started:
            try:
                client.sendall(make_error(error.status, error.reason, error.detail))
            except OSError:
                pass
        print(f"{client_address}: {target} -> {error.status} ({error.detail})")
    except OSError as exc:
        print(f"{client_address}: client connection error: {exc}")
    finally:
        if origin is not None:
            origin.close()


def start_proxy(
    address: str, port: int, client_timeout: float, origin_timeout: float
) -> None:
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
                    handle_client(client, client_address, client_timeout, origin_timeout)
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        start_proxy(
            args.address, args.port, args.client_timeout, args.origin_timeout
        )
    except OSError as exc:
        print(f"proxy: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
