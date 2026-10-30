#!/usr/bin/env python3
"""A deliberately small HTTP/1.1 file server using only sockets."""

from __future__ import annotations

import argparse
import mimetypes
from pathlib import Path
import socket
from urllib.parse import unquote_to_bytes, urlsplit


MAX_HEADER_BYTES = 16 * 1024
READ_CHUNK = 4096


class HTTPError(Exception):
    def __init__(self, status: int, reason: str, detail: str, headers=None):
        super().__init__(detail)
        self.status = status
        self.reason = reason
        self.detail = detail
        self.headers = headers or {}


def read_request_headers(connection: socket.socket) -> bytes:
    """Read through CRLF CRLF, even when TCP splits the request."""
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = connection.recv(READ_CHUNK)
        if not chunk:
            raise HTTPError(400, "Bad Request", "connection closed during headers")
        data.extend(chunk)
        if len(data) > MAX_HEADER_BYTES:
            raise HTTPError(431, "Request Header Fields Too Large", "headers too large")
    header_block, _, _ = bytes(data).partition(b"\r\n\r\n")
    return header_block


def parse_request(header_block: bytes) -> tuple[str, str, str, dict[str, str]]:
    try:
        text = header_block.decode("iso-8859-1")
    except UnicodeDecodeError as exc:
        raise HTTPError(400, "Bad Request", "invalid header bytes") from exc
    lines = text.split("\r\n")
    parts = lines[0].split()
    if len(parts) != 3:
        raise HTTPError(400, "Bad Request", "malformed request line")
    method, target, version = parts
    if version != "HTTP/1.1":
        raise HTTPError(400, "Bad Request", "only HTTP/1.1 is supported")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            raise HTTPError(400, "Bad Request", "malformed request header")
        name, value = line.split(":", 1)
        name = name.strip().lower()
        if not name or name in headers:
            raise HTTPError(400, "Bad Request", "invalid or duplicate header")
        headers[name] = value.strip()
    if "host" not in headers:
        raise HTTPError(400, "Bad Request", "HTTP/1.1 requires Host")
    return method, target, version, headers


def locate_file(document_root: Path, request_target: str) -> Path:
    parsed = urlsplit(request_target)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
        raise HTTPError(400, "Bad Request", "expected an origin-form request target")
    try:
        decoded_path = unquote_to_bytes(parsed.path).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPError(400, "Bad Request", "path is not valid UTF-8") from exc
    if "\x00" in decoded_path or "\\" in decoded_path:
        raise HTTPError(400, "Bad Request", "invalid path")

    relative = decoded_path.lstrip("/") or "index.html"
    root = document_root.resolve()
    candidate = (root / relative).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPError(403, "Forbidden", "path leaves the document root") from exc
    if not candidate.exists() or not candidate.is_file():
        raise HTTPError(404, "Not Found", "file does not exist")
    return candidate


def make_response(
    status: int,
    reason: str,
    body: bytes,
    content_type: str,
    extra_headers: dict[str, str] | None = None,
) -> bytes:
    headers = {
        "Content-Type": content_type,
        "Content-Length": str(len(body)),
        "Connection": "close",
    }
    if extra_headers:
        headers.update(extra_headers)
    head = [f"HTTP/1.1 {status} {reason}"]
    head.extend(f"{name}: {value}" for name, value in headers.items())
    return ("\r\n".join(head) + "\r\n\r\n").encode("iso-8859-1") + body


def error_response(error: HTTPError) -> bytes:
    body = f"{error.status} {error.reason}\n{error.detail}\n".encode("utf-8")
    return make_response(
        error.status,
        error.reason,
        body,
        "text/plain; charset=utf-8",
        error.headers,
    )


def handle_request(
    connection: socket.socket, client_address, document_root: Path, timeout: float
) -> None:
    connection.settimeout(timeout)
    try:
        header_block = read_request_headers(connection)
        method, target, _, _ = parse_request(header_block)
        if method != "GET":
            raise HTTPError(
                405, "Method Not Allowed", "only GET is supported", {"Allow": "GET"}
            )
        file_path = locate_file(document_root, target)
        body = file_path.read_bytes()
        media_type, _ = mimetypes.guess_type(file_path.name)
        if media_type is None:
            media_type = "application/octet-stream"
        elif media_type.startswith("text/"):
            media_type += "; charset=utf-8"
        response = make_response(200, "OK", body, media_type)
        connection.sendall(response)
        print(f"{client_address[0]}:{client_address[1]} GET {target} -> 200")
    except socket.timeout:
        error = HTTPError(408, "Request Timeout", "request headers timed out")
        try:
            connection.sendall(error_response(error))
        except OSError:
            pass
        print(f"{client_address}: request timed out")
    except HTTPError as error:
        try:
            connection.sendall(error_response(error))
        except OSError:
            pass
        print(f"{client_address}: -> {error.status} ({error.detail})")
    except OSError as exc:
        print(f"{client_address}: connection error: {exc}")


def start_server(address: str, port: int, document_root: Path, timeout: float) -> None:
    root = document_root.resolve()
    if not root.is_dir():
        raise ValueError(f"document root is not a directory: {root}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((address, port))
        server.listen()
        shown_address = address or "0.0.0.0"
        print(f"Serving {root} on http://{shown_address}:{port}")
        try:
            while True:
                connection, client_address = server.accept()
                with connection:
                    handle_request(connection, client_address, root, timeout)
        except KeyboardInterrupt:
            print("\nServer stopped")


# Names retained for readers comparing this solution with the supplied skeleton.
handleRequest = handle_request
startServer = start_server


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
    parser = argparse.ArgumentParser(description="Socket-based HTTP/1.1 file server")
    parser.add_argument("--address", default="127.0.0.1")
    parser.add_argument("--port", type=valid_port, default=8000)
    parser.add_argument(
        "--directory", type=Path, default=Path(__file__).resolve().parent
    )
    parser.add_argument("--timeout", type=positive_float, default=5.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        start_server(args.address, args.port, args.directory, args.timeout)
    except (OSError, ValueError) as exc:
        print(f"server: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
