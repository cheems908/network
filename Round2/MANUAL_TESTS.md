# CNSCC231 Round 2 manual tests

Run the cases in order from the `Round2` directory. Use three terminals. Start the origin in terminal 1 and the proxy in terminal 2, then run the client commands in terminal 3. Record the operating system, Python version and test date in `README.txt`.

```text
python3 -u WebServer.py --address 127.0.0.1 --port 8000 --directory .
python3 -u ProxyServer.py --address 127.0.0.1 --port 8080
```

Run one startup command per terminal. If either port is in use, choose another unused local port above 1024 and update the startup command, URLs and capture filter accordingly. On Windows, use `py` and `curl.exe` in Command Prompt. Quotes below work in Command Prompt and POSIX shells. Create the output directory once per test run. Choose a different empty directory if you need to preserve an earlier run.

```text
mkdir evidence
```

## S1 · Web Server returns two existing files

```text
curl --noproxy "*" --http1.1 -sS -D evidence/S1-index-headers.txt -o evidence/S1-index.html http://127.0.0.1:8000/index.html
curl --noproxy "*" --http1.1 -sS -D evidence/S1-second-headers.txt -o evidence/S1-second.html http://127.0.0.1:8000/files/second.html
```

Both responses should show `HTTP/1.1 200 OK`, `Content-Type: text/html; charset=utf-8` and `Connection: close`. For each response, compare `Content-Length` with the downloaded byte count and compare the downloaded body with its source.

```text
wc -c evidence/S1-index.html evidence/S1-second.html
cmp index.html evidence/S1-index.html
cmp files/second.html evidence/S1-second.html
```

On Windows, use `fc /b index.html evidence\S1-index.html` and `fc /b files\second.html evidence\S1-second.html`. Use `dir evidence\S1-*.html` for byte counts. Keep the headers and record both comparison results and byte counts. Both requests should succeed without restarting the server.

For the demonstration, explain that the server accumulates data from successive `recv()` calls until it sees the blank line `\r\n\r\n`. TCP can split that delimiter across calls. In the response, the blank line separates headers from the body and `Content-Length` measures the body in bytes.

## S2 · Web Server handles a missing file

Confirm that `round2-missing-file.html` does not exist in the serving directory.

```text
curl --noproxy "*" --http1.1 -sS -i http://127.0.0.1:8000/round2-missing-file.html > evidence/S2-missing.txt
curl --noproxy "*" --http1.1 -sS -i http://127.0.0.1:8000/index.html > evidence/S2-recovery.txt
```

Expect `404 Not Found` with an error body, then `200 OK` from the same server process. Record both observed statuses.

## P1 · Compare direct and proxied requests

Start a Wireshark capture on the loopback interface before running these commands. Use display filter `tcp.port == 8000 || tcp.port == 8080`.

```text
curl --noproxy "*" --http1.1 -sS -D evidence/P1-direct-headers.txt -o evidence/P1-direct.html http://127.0.0.1:8000/index.html
curl --noproxy "" --http1.1 -sS -v -x http://127.0.0.1:8080 -D evidence/P1-proxy-headers.txt -o evidence/P1-proxy.html http://127.0.0.1:8000/index.html 2> evidence/P1-client-trace.txt
cmp evidence/P1-direct.html evidence/P1-proxy.html
```

On Windows, replace `cmp` with `fc /b evidence\P1-direct.html evidence\P1-proxy.html`. Expect 200 responses with matching `Content-Type` and `Content-Length`, and identical bodies. Follow the TCP streams in Wireshark and record the stream IDs and ports for the proxied request.

- Client ephemeral port → 8080. Expect `GET http://127.0.0.1:8000/index.html HTTP/1.1`.
- Proxy ephemeral port → 8000. Expect `GET /index.html HTTP/1.1` and `Host: 127.0.0.1:8000`. The origin response on this stream shows that the proxy reached the origin. The direct request also goes to 8000, so use the order of the requests to distinguish it from the proxy's origin connection.

Save the capture as `evidence/P1-loopback.pcapng`. If loopback capture is unavailable, record that limitation and save the verbose curl trace together with the origin and proxy logs from the proxied request. Identify the client port from the proxy log and the proxy's origin-side source port from the origin log.

## P2 · Fetch a different path through the proxy

```text
curl --noproxy "" --http1.1 -sS -x http://127.0.0.1:8080 -D evidence/P2-headers.txt -o evidence/P2-second.html http://127.0.0.1:8000/files/second.html
cmp files/second.html evidence/P2-second.html
```

On Windows, use `fc /b files\second.html evidence\P2-second.html`. Expect `200 OK` and exact agreement with the second file. Record the status and comparison result.

## P3 · Origin unavailable and proxy recovery

Stop only the origin with Ctrl+C. Leave the proxy running.

```text
curl --noproxy "" --http1.1 -sS -i -x http://127.0.0.1:8080 http://127.0.0.1:8000/index.html > evidence/P3-origin-down.txt
```

Expect `502 Bad Gateway`. Restart the origin using its startup command and wait for the listening message. With the same proxy process still running, repeat the request.

```text
curl --noproxy "" --http1.1 -sS -i -x http://127.0.0.1:8080 http://127.0.0.1:8000/index.html > evidence/P3-recovery.txt
```

Expect `200 OK` and the contents of `index.html`. Record both statuses and keep the proxy log for the failure and recovery.

## Record and submit

For each case, record the observed result, whether it matched the expected result, and the relative evidence filenames in section 3 of `README.txt`. Include relevant comparison results and the two connection endpoints for P1. Put any cases you could not run and the reasons in section 4. Include the referenced evidence, this guide and the served files in the Round 2 ZIP. The coursework sets an 800-word limit for the README excluding copied output.
