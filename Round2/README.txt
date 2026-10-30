CNSCC231 Round 2

1. Team and environment

Team: [TEAM NUMBER]. Members: [ADD ALL SIX NAMES AND STUDENT IDS]. Development checks were run on Ubuntu Linux 7.0.0-38-generic with Python 3.14.4 on 28 October 2026. Repeat the demonstrations on the final course-accepted Windows or macOS machine and replace this environment entry before submission.

2. How to run

Open two terminals in Round2. No third-party packages are used.

Terminal 1:

    python3 WebServer.py --address 127.0.0.1 --port 8000 --directory .

Terminal 2:

    python3 ProxyServer.py --address 127.0.0.1 --port 8080

Direct request:

    curl -i http://127.0.0.1:8000/index.html

Forced proxy request (the empty `--noproxy` prevents curl bypassing localhost):

    curl --noproxy "" -x http://127.0.0.1:8080 http://127.0.0.1:8000/index.html -D proxy-headers.txt -o proxy-body.html

Use `py` in place of `python3` on Windows if needed. Both programs handle one request per connection, close it, and continue accepting later connections. `--help` documents configurable timeouts and ports.

3. Tests and findings

R2-SERVER-01 (normal and framing): `python3 -m unittest discover -s tests -v`. A GET header was sent in three writes. Expected: the server waits for CRLF-CRLF, ignores the query when locating the file, and reports the UTF-8 body's encoded byte length. Actual: 200, exact bytes and correct Content-Length. A sample binary body also matched by SHA-256.

R2-SERVER-02 (failure/security): missing file, POST, encoded `..`, and a symlink to an external file. Expected: 404, 405 with Allow: GET, and 403 for both escape attempts. Actual: all passed and later test requests still worked.

R2-PROXY-03 (normal): a local origin split a 2,048-byte generated binary body over multiple sends. Expected: the proxy rewrites the absolute URL to origin-form, rebuilds Host with the non-default port, adds Connection: close, and relays every response byte. Actual: request headers matched and the complete response was byte-identical.

R2-PROXY-04 (failure): a closed local origin port, HTTPS URL and CONNECT. Expected: 502, 400 and 405 respectively. Actual: all passed; no process restart was needed. Evidence for all cases: `evidence/AUTOMATED_TESTS.txt`.

Before submission, save curl headers/body hashes plus server and proxy logs or a pcap showing client-to-proxy and proxy-to-origin TCP connections. Modify a served file and request it again to demonstrate there is no stale cache.

4. Limitations

The programs support plain HTTP/1.1 GET only, one request per connection. They do not implement TLS, CONNECT, caching, persistent connections or concurrency. The proxy transparently streams close-delimited, Content-Length and chunked framing; it logs a Content-Length mismatch but cannot replace a response after any bytes have reached the client. A slow client can delay this intentionally single-threaded design.

5. Contributions and sources

[REPLACE WITH EACH MEMBER'S CONTRIBUTION.] The coursework starter supplied the initial Web Server skeleton and sample page; the implementation was rewritten and checked against the coursework PDF and Python standard-library documentation. OpenAI Codex assisted with implementation, fixtures, tests and notes. The team must review the code, repeat every claimed test, and be able to explain TCP framing, byte lengths, path containment, request rewriting and the proxy's two TCP connections.
