CNSCC231 Round 2

1. Team and environment

Team: [TEAM NUMBER]. Members: [ADD ALL SIX NAMES AND STUDENT IDS]. Manual test environment: [OS AND VERSION, PYTHON VERSION, TEST DATE].

2. How to run

Open two terminals in Round2. Start the Web Server first, then the Proxy. No third-party packages are used. Keep index.html and files/second.html for the manual tests.

Terminal 1:

    python3 WebServer.py --address 127.0.0.1 --port 8000 --directory .

Terminal 2:

    python3 ProxyServer.py --address 127.0.0.1 --port 8080

Direct request:

    curl --noproxy "*" -i http://127.0.0.1:8000/index.html

Forced proxy request (the empty `--noproxy` prevents curl bypassing localhost):

    curl --noproxy "" -x http://127.0.0.1:8080 http://127.0.0.1:8000/index.html -i

Use `py` in place of `python3` on Windows if needed. Both programs handle one request per connection, close it, and continue accepting later connections. `--help` documents configurable timeouts and ports.

3. Tests and findings

See MANUAL_TESTS.md for commands and evidence collection. Include the
guide and the referenced evidence in the submission ZIP.

S1. Requested index.html and files/second.html directly. Expected two
200 responses with correct headers and matching bodies. Both returned
200 OK with Content-Length: 170 and Connection: close. Each 170-byte body
matched its source file byte for byte.
Evidence: evidence/S1-index-headers.txt, evidence/S1-index.html,
evidence/S1-second-headers.txt and evidence/S1-second.html.

S2. Requested a missing file, then requested index.html. Expected 404
followed by 200. Observed 404 Not Found with a file-does-not-exist message,
then 200 OK for the valid file.
Evidence: evidence/S2-missing.txt and evidence/S2-recovery.txt.

P1. Requested index.html directly and through the proxy. Expected matching
200 responses and two TCP connections for the proxied request. Both
responses returned 200 OK with identical headers and 170-byte bodies
that matched index.html. On loopback, the client connected from port 49088
to proxy port 8080 and sent the absolute URL. The proxy connected from
port 38480 to origin port 8000 and sent GET /index.html HTTP/1.1 with
Host: 127.0.0.1:8000. The direct comparison used ports 57292 to 8000.
Evidence: evidence/P1-loopback.pcapng, evidence/P1-client-trace.txt,
evidence/P1-direct-headers.txt, evidence/P1-proxy-headers.txt,
evidence/P1-direct.html and evidence/P1-proxy.html.

P2. Changed the proxied path to /files/second.html. Expected 200 and the
second file's contents. Observed 200 OK with Content-Length: 170, and the
download matched files/second.html byte for byte.
Evidence: evidence/P2-headers.txt and evidence/P2-second.html.

P3. Stopped the origin and requested index.html through the proxy, then
restarted the origin and repeated the request. Expected 502 while the
origin was down and 200 after it restarted. Observed 502 Bad Gateway
with an origin connection refused error, then 200 OK with a body that
matched index.html byte for byte.
Evidence: evidence/P3-origin-down.txt and evidence/P3-recovery.txt.

The server accumulates bytes across recv() calls and recognises the end
of the request headers at CRLF-CRLF. A TCP receive call can return only
part of the headers, including part of the delimiter.

4. Limitations

The programs support plain HTTP/1.1 GET only, one request per connection.
They do not implement TLS, CONNECT, caching, persistent connections or concurrency.
The proxy transparently streams close-delimited, Content-Length and chunked framing;
it logs a Content-Length mismatch
but cannot replace a response after any bytes have reached the client.
A slow client can delay this intentionally single-threaded design.

5. Contributions and sources

[REPLACE WITH EACH MEMBER'S CONTRIBUTION.] The coursework starter supplied the initial Web Server skeleton and sample page; the implementation was rewritten and checked against the coursework PDF and Python standard-library documentation. OpenAI Codex assisted with implementation, fixtures, tests and notes. The team must review the code, repeat every claimed test, and be able to explain TCP framing, byte lengths, path containment, request rewriting and the proxy's two TCP connections.
