# CNSCC231 Round 2 manual tests

[中文版](MANUAL_TESTS.zh-CN.md)

Run from `Round2`. Start the server in terminal 1 and the proxy in terminal 2. Run requests in a third terminal. Create `evidence/` if absent and back it up before retesting because the commands reuse filenames.

```text
python3 -u WebServer.py --address 127.0.0.1 --port 8000 --directory . --timeout 30
python3 -u ProxyServer.py --address 127.0.0.1 --port 8080
```

On Windows Command Prompt, use `py`, `curl.exe`, `fc /b` in place of `cmp`, and `dir` for file sizes. To demonstrate configurable ports, rerun a proxied download with both ports changed, for example to 8001 and 8081. Update the URLs and capture filter to match.

## 1. Web Server and concurrency

**Files and 404.** Run both GET requests against the same server process. Check `200 OK`, `Content-Type`, `Connection: close` and that each `Content-Length` matches the saved byte count. Compare each body to its source. Confirm the missing test path is absent and check `404 → 200` in the last two outputs.

```text
curl --noproxy "*" --http1.1 -sS -D evidence/S1-index-headers.txt -o evidence/S1-index.html http://127.0.0.1:8000/index.html
curl --noproxy "*" --http1.1 -sS -D evidence/S1-second-headers.txt -o evidence/S1-second.html http://127.0.0.1:8000/files/second.html
wc -c evidence/S1-index.html evidence/S1-second.html
cmp index.html evidence/S1-index.html
cmp files/second.html evidence/S1-second.html
curl --noproxy "*" --http1.1 -sS -i http://127.0.0.1:8000/round2-missing-file.html > evidence/S2-missing.txt
curl --noproxy "*" --http1.1 -sS -i http://127.0.0.1:8000/index.html > evidence/S2-recovery.txt
```

**Concurrent requests.** Run the Python command in client terminal A. While it waits for Enter, run curl in terminal B within 30 seconds. Open `evidence/E1-client-B.txt` and confirm `200 OK` before pressing Enter in A. A should then return `200 OK`. Save both outputs and record the order.

```text
python3 -c "import socket; s = socket.create_connection(('127.0.0.1', 8000)); s.sendall(b'GET /index.html HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n'); input('Headers unfinished. Run client B, then press Enter: '); s.sendall(b'\r\n'); print(s.makefile('rb').read().decode()); s.close()"
```

```text
curl --noproxy "*" --http1.1 -sS -i http://127.0.0.1:8000/index.html > evidence/E1-client-B.txt
```

Explain that the server assembles request bytes across `recv()` calls until `\r\n\r\n` arrives. In the response that delimiter separates headers from the body.

## 2. Proxy forwarding, standalone client and HEAD

**Direct versus proxy.** Capture on the Wireshark loopback interface with display filter `tcp.port == 8000 || tcp.port == 8080`. Expect two `200 OK` responses with the same headers and body.

```text
curl --noproxy "*" --http1.1 -sS -D evidence/P1-direct-headers.txt -o evidence/P1-direct.html http://127.0.0.1:8000/index.html
curl --noproxy "" --http1.1 -sS -v -x http://127.0.0.1:8080 -D evidence/P1-proxy-headers.txt -o evidence/P1-proxy.html http://127.0.0.1:8000/index.html 2> evidence/P1-client-trace.txt
cmp evidence/P1-direct.html evidence/P1-proxy.html
```

Save `evidence/P1-loopback.pcapng` and record the two proxied TCP streams. The client connects to 8080 and sends an absolute URL. The proxy connects from a different source port to 8000, sends `GET /index.html` with `Host: 127.0.0.1:8000` and receives the origin response. If capture is unavailable, record that limitation and use the curl trace plus matching proxy and origin logs to show both endpoints.

**Different path and standalone client.** Check `200 OK` and the byte comparisons for the second path and both client downloads.

```text
curl --noproxy "" --http1.1 -sS -x http://127.0.0.1:8080 -D evidence/P2-headers.txt -o evidence/P2-second.html http://127.0.0.1:8000/files/second.html
cmp files/second.html evidence/P2-second.html
python3 HTTPClient.py http://127.0.0.1:8000/index.html -o evidence/E2-direct.html > evidence/E2-direct-headers.txt
python3 HTTPClient.py http://127.0.0.1:8000/index.html --proxy http://127.0.0.1:8080 -o evidence/E2-proxy.html > evidence/E2-proxy-headers.txt
cmp index.html evidence/E2-direct.html
cmp index.html evidence/E2-proxy.html
```

**HEAD.** Compare status, `Content-Type` and `Content-Length` with the corresponding GET. Start a separate loopback capture before these commands. Verify `HEAD /index.html` on the origin connection and that both responses to the proxied request contain headers only. Save the capture as `evidence/E3-head.pcapng`.

```text
curl --noproxy "*" --http1.1 -sS -I http://127.0.0.1:8000/index.html > evidence/E3-direct-head.txt
curl --noproxy "" --http1.1 -sS -I -x http://127.0.0.1:8080 http://127.0.0.1:8000/index.html > evidence/E3-proxy-head.txt
```

## 3. Origin failure and recovery

Stop only the Web Server with Ctrl+C. Confirm a direct connection to port 8000 is refused, then request through the still-running proxy and check for `502 Bad Gateway`.

```text
curl --noproxy "*" --connect-timeout 3 -sS http://127.0.0.1:8000/index.html
curl --noproxy "" --http1.1 -sS -i -x http://127.0.0.1:8080 http://127.0.0.1:8000/index.html > evidence/P3-origin-down.txt
```

Restart the Web Server with the setup command. Repeat through the same proxy process and check for `200 OK` and the `index.html` body.

```text
curl --noproxy "" --http1.1 -sS -i -x http://127.0.0.1:8080 http://127.0.0.1:8000/index.html > evidence/P3-recovery.txt
```

## 4. Cache miss and hit

Restart both services in their original terminals with these commands.

```text
python3 -u WebServer.py --address 127.0.0.1 --port 8000 --directory . --cache-file files/second.html
python3 -u ProxyServer.py --address 127.0.0.1 --port 8080 --cache
```

Run the same URL twice within 30 seconds. Expect two `200 OK` responses and matching bodies. Save the response files and both logs. The proxy must log `MISS → HIT`, the second response must contain `Age`, and the origin should log one GET for this URL. Use a new query value for a fresh run.

```text
curl --noproxy "" --http1.1 -sS -x http://127.0.0.1:8080 -D evidence/E4-miss-headers.txt -o evidence/E4-miss.html "http://127.0.0.1:8000/files/second.html?cache=demo"
curl --noproxy "" --http1.1 -sS -x http://127.0.0.1:8080 -D evidence/E4-hit-headers.txt -o evidence/E4-hit.html "http://127.0.0.1:8000/files/second.html?cache=demo"
cmp files/second.html evidence/E4-miss.html
cmp files/second.html evidence/E4-hit.html
```

## Record results

In `README.txt`, record the environment, expected and observed outcomes, evidence paths and any checks you could not run. Include the referenced files and `HTTPClient.py` in the submission ZIP.
