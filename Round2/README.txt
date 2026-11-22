CNSCC231 Round 2

1. Team and environment

Team: [TEAM NUMBER]. Members: [ADD ALL SIX NAMES AND STUDENT IDS]. Manual retest: 22 November 2026. Environment: [OS AND VERSION, PYTHON VERSION].

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

Use `py` in place of `python3` on Windows if needed. Both programs close
each connection after one request. The Web Server defaults to four workers
and accepts `--workers`. Both programs support GET and HEAD. To download
through the proxy with the submitted socket client, run:

    python3 HTTPClient.py http://127.0.0.1:8000/index.html --proxy http://127.0.0.1:8080 -o downloaded.html

The cache is opt-in. Start the Web Server with `--cache-file files/second.html`
and the Proxy with `--cache` for the cache demonstration in MANUAL_TESTS.md.

3. Tests and findings

See MANUAL_TESTS.md or MANUAL_TESTS.zh-CN.md for commands. Include the
guide, referenced evidence and HTTPClient.py with the two server programs.

Web Server and concurrency

The two direct file requests were expected to return 200 with matching
bodies. Both returned 200 OK, Content-Length: 170 and Connection: close.
Each 170-byte body matched its own source. A missing path returned 404,
then a valid request returned 200 on the same server, as expected.
Evidence: evidence/S1-index-headers.txt, evidence/S1-index.html,
evidence/S1-second-headers.txt, evidence/S1-second.html,
evidence/S2-missing.txt and evidence/S2-recovery.txt.

The server accumulates bytes across recv() calls until CRLF-CRLF, which
can span calls. With two workers, A sent an unfinished request. B was
expected to finish first and did receive 200 OK before A sent the final
blank line. A then received 200 OK.
Evidence: evidence/E1-order.txt, evidence/E1-client-A.txt and
evidence/E1-client-B.txt.

Proxy forwarding, standalone client and HEAD

Direct and proxied GETs for index.html were expected to match. Both
returned 200 OK with identical headers and bodies. The loopback capture
shows client 54626 → proxy 8080 carrying the absolute URL, and proxy
60176 → origin 8000 carrying GET /index.html HTTP/1.1 with
Host: 127.0.0.1:8000. Direct traffic used 40930 → 8000.
Evidence: evidence/P1-loopback.pcapng, evidence/P1-client-trace.txt,
evidence/P1-direct-headers.txt, evidence/P1-proxy-headers.txt,
evidence/P1-direct.html and evidence/P1-proxy.html.

The proxy returned 200 OK and the matching file after the path changed to
/files/second.html. HTTPClient.py also returned 200 OK and downloaded
byte-identical copies of index.html directly and through the proxy.
Evidence: evidence/P2-headers.txt, evidence/P2-second.html,
evidence/E2-direct-headers.txt, evidence/E2-direct.html,
evidence/E2-proxy-headers.txt and evidence/E2-proxy.html.

Direct and proxied HEAD were expected to match the corresponding GET
status and representation headers. Both showed 200 OK, the same
Content-Type and Content-Length: 170.
Evidence: evidence/E3-direct-head.txt and evidence/E3-proxy-head.txt.

Origin failure and recovery

Expected 502 while the origin was stopped and 200 after restart.
With port 8000 refusing connections, the proxy returned 502 Bad Gateway.
After the origin restarted, the same proxy returned 200 OK with the
matching index.html body.
Evidence: evidence/P3-origin-down.txt and evidence/P3-recovery.txt.

Cache miss and hit

Requested the same cacheable URL twice within 30 seconds, expecting
a miss followed by a hit. Both responses were 200 OK and matched
files/second.html. Both carried the same Date and max-age=30. Only
the second included Age: 9, which indicates a cached response.
Evidence: evidence/E4-miss-headers.txt, evidence/E4-miss.html,
evidence/E4-hit-headers.txt and evidence/E4-hit.html.

4. Limitations

The programs use plain HTTP/1.1 without TLS, CONNECT or persistent connections.
The GET-only client accepts Content-Length and close-delimited bodies.
The single-threaded proxy streams GET responses and logs Content-Length
mismatches. Its optional cache accepts complete public GET responses with
an explicit max-age, a Date and a matching Content-Length. It stores at most
16 responses of up to 256 KiB each for at most 60 seconds, without revalidation.
The manual HEAD records contain client headers only. A HEAD packet capture
and the cache demonstration service logs were unavailable.

5. Contributions and sources

[REPLACE WITH EACH MEMBER'S CONTRIBUTION.] The coursework starter supplied the initial Web Server skeleton and sample page; the implementation was rewritten and checked against the coursework PDF and Python standard-library documentation. OpenAI Codex assisted with implementation, fixtures, tests and notes. The team must review the code, repeat every claimed test, and be able to explain TCP framing, byte lengths, path containment, request rewriting and the proxy's two TCP connections.
