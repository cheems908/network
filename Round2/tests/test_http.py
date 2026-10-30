import hashlib
from pathlib import Path
import socket
import tempfile
import threading
import unittest

import ProxyServer
import WebServer


ROOT = Path(__file__).resolve().parents[1]


def run_handler(handler, server_socket, *args):
    try:
        handler(server_socket, ("local-test", 12345), *args)
    finally:
        server_socket.close()


def socketpair_exchange(handler, request_parts, *args):
    client, server = socket.socketpair()
    thread = threading.Thread(target=run_handler, args=(handler, server, *args))
    thread.start()
    with client:
        for part in request_parts:
            client.sendall(part)
        client.shutdown(socket.SHUT_WR)
        response = bytearray()
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            response.extend(chunk)
    thread.join(2)
    if thread.is_alive():
        raise AssertionError("handler did not finish")
    return bytes(response)


def split_response(response):
    head, separator, body = response.partition(b"\r\n\r\n")
    if not separator:
        raise AssertionError("response has no header terminator")
    headers = {}
    lines = head.decode("iso-8859-1").split("\r\n")
    for line in lines[1:]:
        name, value = line.split(":", 1)
        headers[name.lower()] = value.strip()
    return lines[0], headers, body


class WebServerTests(unittest.TestCase):
    def request(self, target, parts=1, method="GET"):
        raw = f"{method} {target} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode()
        request_parts = [raw] if parts == 1 else [raw[:8], raw[8:21], raw[21:]]
        return socketpair_exchange(
            WebServer.handle_request, request_parts, ROOT, 1.0
        )

    def test_fragmented_request_returns_complete_utf8_file(self):
        response = self.request("/files/utf8.txt?ignored=yes", parts=3)
        status, headers, body = split_response(response)
        expected = (ROOT / "files/utf8.txt").read_bytes()
        self.assertEqual(status, "HTTP/1.1 200 OK")
        self.assertEqual(body, expected)
        self.assertEqual(int(headers["content-length"]), len(expected))
        self.assertGreater(len(expected), len(expected.decode("utf-8")))

    def test_binary_file_is_returned_byte_for_byte(self):
        response = self.request("/files/sample.bin")
        _, headers, body = split_response(response)
        expected = (ROOT / "files/sample.bin").read_bytes()
        self.assertEqual(hashlib.sha256(body).digest(), hashlib.sha256(expected).digest())
        self.assertEqual(int(headers["content-length"]), len(expected))

    def test_missing_method_and_traversal_errors(self):
        self.assertTrue(split_response(self.request("/missing"))[0].endswith("404 Not Found"))
        self.assertTrue(split_response(self.request("/index.html", method="POST"))[0].endswith("405 Method Not Allowed"))
        self.assertTrue(split_response(self.request("/%2e%2e/secret"))[0].endswith("403 Forbidden"))

    def test_symlink_cannot_escape_document_root(self):
        with tempfile.TemporaryDirectory() as root_name, tempfile.TemporaryDirectory() as outside_name:
            root = Path(root_name)
            outside = Path(outside_name) / "secret.txt"
            outside.write_text("secret", encoding="utf-8")
            (root / "escape").symlink_to(outside)
            with self.assertRaises(WebServer.HTTPError) as caught:
                WebServer.locate_file(root, "/escape")
            self.assertEqual(caught.exception.status, 403)


class ProxyTests(unittest.TestCase):
    def start_origin(self, response_parts):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        observed = []

        def serve():
            with listener:
                connection, _ = listener.accept()
                with connection:
                    request = bytearray()
                    while b"\r\n\r\n" not in request:
                        request.extend(connection.recv(4096))
                    observed.append(bytes(request))
                    for part in response_parts:
                        connection.sendall(part)

        thread = threading.Thread(target=serve)
        thread.start()
        return port, observed, thread

    def test_proxy_rewrites_target_and_relays_binary_response(self):
        body = bytes(range(256)) * 8
        upstream = (
            b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n"
            + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body
        )
        port, observed, origin_thread = self.start_origin(
            [upstream[:37], upstream[37:1000], upstream[1000:]]
        )
        target = f"http://127.0.0.1:{port}/files/sample.bin?version=2"
        request = (
            f"GET {target} HTTP/1.1\r\nHost: ignored.example\r\n\r\n".encode()
        )
        response = socketpair_exchange(
            ProxyServer.handle_client, [request], 1.0, 1.0
        )
        origin_thread.join(2)
        self.assertEqual(response, upstream)
        self.assertIn(
            b"GET /files/sample.bin?version=2 HTTP/1.1\r\n", observed[0]
        )
        self.assertIn(f"Host: 127.0.0.1:{port}\r\n".encode(), observed[0])
        self.assertIn(b"Connection: close\r\n", observed[0])

    def test_unavailable_origin_returns_502_and_proxy_can_run_again(self):
        unused = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        unused.bind(("127.0.0.1", 0))
        port = unused.getsockname()[1]
        unused.close()
        request = (
            f"GET http://127.0.0.1:{port}/ HTTP/1.1\r\nHost: x\r\n\r\n".encode()
        )
        response = socketpair_exchange(
            ProxyServer.handle_client, [request], 1.0, 0.2
        )
        self.assertTrue(split_response(response)[0].endswith("502 Bad Gateway"))

        upstream = (
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n"
            b"Connection: close\r\n\r\nOK"
        )
        recovered_port, _, origin_thread = self.start_origin([upstream])
        recovered_request = (
            f"GET http://127.0.0.1:{recovered_port}/after-failure HTTP/1.1\r\n"
            "Host: ignored\r\n\r\n"
        ).encode()
        recovered = socketpair_exchange(
            ProxyServer.handle_client, [recovered_request], 1.0, 1.0
        )
        origin_thread.join(2)
        self.assertEqual(recovered, upstream)

    def test_https_and_connect_are_rejected(self):
        https = b"GET https://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n"
        response = socketpair_exchange(
            ProxyServer.handle_client, [https], 1.0, 1.0
        )
        self.assertTrue(split_response(response)[0].endswith("400 Bad Request"))
        connect = b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com\r\n\r\n"
        response = socketpair_exchange(
            ProxyServer.handle_client, [connect], 1.0, 1.0
        )
        self.assertTrue(split_response(response)[0].endswith("405 Method Not Allowed"))


if __name__ == "__main__":
    unittest.main()
