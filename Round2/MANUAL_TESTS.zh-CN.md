# CNSCC231 Round 2 手动测试流程

[English version](MANUAL_TESTS.md)

在 `Round2` 目录运行。终端 1 启动 Web Server，终端 2 启动代理，终端 3 执行请求。若没有 `evidence/` 目录就先创建。重测会沿用文件名，如需保留旧证据请先备份。

```text
python3 -u WebServer.py --address 127.0.0.1 --port 8000 --directory . --timeout 30
python3 -u ProxyServer.py --address 127.0.0.1 --port 8080
```

Windows 命令提示符中用 `py`、`curl.exe`，用 `fc /b` 替代 `cmp`，用 `dir` 查看文件字节数。要演示端口可配置，可把两个端口改为 8001 和 8081，再通过代理下载一次，并同步修改 URL 和抓包过滤器。

## 1. Web Server 与并发

**文件与 404。** 保持同一个 Web Server 进程运行。两个文件均应返回 `200 OK`，核对 `Content-Type`、`Connection: close` 和 `Content-Length`，并用字节数和文件比较确认响应体完整。确认缺失路径确实不存在，最后两次请求应依次返回 `404 → 200`。

```text
curl --noproxy "*" --http1.1 -sS -D evidence/S1-index-headers.txt -o evidence/S1-index.html http://127.0.0.1:8000/index.html
curl --noproxy "*" --http1.1 -sS -D evidence/S1-second-headers.txt -o evidence/S1-second.html http://127.0.0.1:8000/files/second.html
wc -c evidence/S1-index.html evidence/S1-second.html
cmp index.html evidence/S1-index.html
cmp files/second.html evidence/S1-second.html
curl --noproxy "*" --http1.1 -sS -i http://127.0.0.1:8000/round2-missing-file.html > evidence/S2-missing.txt
curl --noproxy "*" --http1.1 -sS -i http://127.0.0.1:8000/index.html > evidence/S2-recovery.txt
```

**并发。** 在客户端终端 A 运行 Python 命令。A 等待回车时，在 30 秒内从客户端终端 B 执行 curl。打开 `evidence/E1-client-B.txt` 确认 `200 OK`，再回到 A 按回车，A 也应返回 `200 OK`。保存两边的输出并记录先后顺序。

```text
python3 -c "import socket; s = socket.create_connection(('127.0.0.1', 8000)); s.sendall(b'GET /index.html HTTP/1.1\r\nHost: 127.0.0.1:8000\r\n'); input('Headers unfinished. Run client B, then press Enter: '); s.sendall(b'\r\n'); print(s.makefile('rb').read().decode()); s.close()"
```

```text
curl --noproxy "*" --http1.1 -sS -i http://127.0.0.1:8000/index.html > evidence/E1-client-B.txt
```

演示时说明服务器会把多次 `recv()` 读到的字节拼接起来，直到收到 `\r\n\r\n`。响应中的同一分隔符用于分开响应头和响应体。

## 2. 代理转发、独立客户端与 HEAD

**直连与代理对照。** 用 Wireshark 抓取回环接口，显示过滤器为 `tcp.port == 8000 || tcp.port == 8080`。预期两次均返回 `200 OK`，响应头和响应体一致。

```text
curl --noproxy "*" --http1.1 -sS -D evidence/P1-direct-headers.txt -o evidence/P1-direct.html http://127.0.0.1:8000/index.html
curl --noproxy "" --http1.1 -sS -v -x http://127.0.0.1:8080 -D evidence/P1-proxy-headers.txt -o evidence/P1-proxy.html http://127.0.0.1:8000/index.html 2> evidence/P1-client-trace.txt
cmp evidence/P1-direct.html evidence/P1-proxy.html
```

将抓包保存为 `evidence/P1-loopback.pcapng`，记录代理请求的两条 TCP 流。客户端连接 8080，发送绝对 URL。代理从另一源端口连接 8000，发送 `GET /index.html` 和 `Host: 127.0.0.1:8000`，并收到源站响应。无法抓包时，在 README 记录限制，使用 curl 跟踪和对应的代理、源站日志证明两条连接。

**不同路径和独立客户端。** 确认第二个路径和客户端的两次下载均返回 `200 OK`，响应体均与各自源文件逐字节一致。

```text
curl --noproxy "" --http1.1 -sS -x http://127.0.0.1:8080 -D evidence/P2-headers.txt -o evidence/P2-second.html http://127.0.0.1:8000/files/second.html
cmp files/second.html evidence/P2-second.html
python3 HTTPClient.py http://127.0.0.1:8000/index.html -o evidence/E2-direct.html > evidence/E2-direct-headers.txt
python3 HTTPClient.py http://127.0.0.1:8000/index.html --proxy http://127.0.0.1:8080 -o evidence/E2-proxy.html > evidence/E2-proxy-headers.txt
cmp index.html evidence/E2-direct.html
cmp index.html evidence/E2-proxy.html
```

**HEAD。** 与对应的 GET 比较状态码、`Content-Type` 和 `Content-Length`。执行命令前另起一次回环抓包，确认代理向源站发送 `HEAD /index.html`，代理链路上的两段响应均只有响应头。保存为 `evidence/E3-head.pcapng`。

```text
curl --noproxy "*" --http1.1 -sS -I http://127.0.0.1:8000/index.html > evidence/E3-direct-head.txt
curl --noproxy "" --http1.1 -sS -I -x http://127.0.0.1:8080 http://127.0.0.1:8000/index.html > evidence/E3-proxy-head.txt
```

## 3. 源站停机与恢复

只在 Web Server 终端按 Ctrl+C。先确认直连 8000 被拒绝，再经仍在运行的代理请求，预期返回 `502 Bad Gateway`。

```text
curl --noproxy "*" --connect-timeout 3 -sS http://127.0.0.1:8000/index.html
curl --noproxy "" --http1.1 -sS -i -x http://127.0.0.1:8080 http://127.0.0.1:8000/index.html > evidence/P3-origin-down.txt
```

用初始命令重启 Web Server。经同一个代理进程再次请求，预期返回 `200 OK`，响应体为 `index.html`。

```text
curl --noproxy "" --http1.1 -sS -i -x http://127.0.0.1:8080 http://127.0.0.1:8000/index.html > evidence/P3-recovery.txt
```

## 4. 缓存未命中与命中

停止两个服务，在各自终端用以下命令重启。

```text
python3 -u WebServer.py --address 127.0.0.1 --port 8000 --directory . --cache-file files/second.html
python3 -u ProxyServer.py --address 127.0.0.1 --port 8080 --cache
```

30 秒内请求同一 URL 两次。预期两次均返回 `200 OK`，响应体一致。保留响应文件和两个服务的日志。代理应依次记录 `MISS → HIT`，第二次响应应含 `Age`，源站只应为该 URL 记录一次 GET。重测时换一个查询参数值。

```text
curl --noproxy "" --http1.1 -sS -x http://127.0.0.1:8080 -D evidence/E4-miss-headers.txt -o evidence/E4-miss.html "http://127.0.0.1:8000/files/second.html?cache=demo"
curl --noproxy "" --http1.1 -sS -x http://127.0.0.1:8080 -D evidence/E4-hit-headers.txt -o evidence/E4-hit.html "http://127.0.0.1:8000/files/second.html?cache=demo"
cmp files/second.html evidence/E4-miss.html
cmp files/second.html evidence/E4-hit.html
```

## 记录结果

在 `README.txt` 记录测试环境、预期及实际结果、证据路径和无法执行的检查。提交 ZIP 中一并包含引用的文件与 `HTTPClient.py`。
