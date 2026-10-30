CNSCC231 Round 1

1. Team and environment

Team: [TEAM NUMBER]. Members: [ADD ALL SIX NAMES AND STUDENT IDS]. Development checks were run on Ubuntu Linux 7.0.0-38-generic with Python 3.14.4 on 28 October 2026. Linux is not the planned assessment platform: replace this sentence after repeating the live tests on the course-accepted Windows or macOS machine. Raw ICMP requires Administrator rights on Windows or typically sudo on macOS.

2. How to run

Work in the Round1 directory. No third-party packages are used.

    python3 ICMPPing.py 127.0.0.1 --count 4 --timeout 1 --interval 1
    python3 Traceroute.py 127.0.0.1 --max-hops 10 --timeout 1 --probes 3
    python3 Traceroute.py <course-approved-host> --max-hops 30

Use `py` instead of `python3` on Windows if required, and start an Administrator terminal. On macOS, prefix the commands with `sudo` if raw sockets are denied. Omit `--count` to run Ping until Ctrl+C. Add `--resolve-names` to Traceroute only when reverse DNS delay is acceptable. `--help` lists every option.

3. Tests and findings

R1-PARSE-01 (normal, simulated packets): `python3 -m unittest discover -s tests -v`. Expected: valid Echo packets have a zero verification checksum; Echo Replies match source, ID and sequence; Time Exceeded and Destination Unreachable match the quoted inner request. Actual: nine tests passed. The IHL-options case, truncated packets, TTL progression, destination stop and silent-hop maximum also passed. Evidence: `evidence/AUTOMATED_TESTS.txt`.

R1-DEADLINE-02 (boundary, simulated packets): an unrelated Echo Reply was supplied before timeout. Expected: reject it and retain the original deadline. Actual: the next wait fell from 0.9 s to 0.7 s, proving the deadline was not restarted. Evidence: the same file and `tests/test_icmp.py`.

R1-LIVE-03 (environment failure): Ping loopback was attempted in the managed Linux development environment. Expected: an Echo Reply if raw sockets are permitted. Actual: raw socket creation was denied and the program gave a clear permission error. Evidence: `evidence/RAW_SOCKET_ENVIRONMENT.txt`. This is not evidence of a live successful Ping or route.

Before submission, record on the final Windows/macOS machine: loopback Ping, comparison with system Ping, loopback Traceroute, and an approved multi-hop target. Save terminal output and a pcap/pcapng showing request ID/sequence, TTL changes, quoted probes and replies. Do not call these tests passed until performed.

4. Limitations

Only IPv4 ICMP Echo probes are implemented. There is no IPv6 or UDP mode. DNS lookups are blocking. Network policy may hide hops; `*` means no matching response arrived by the deadline, not that routing stopped. Live raw-socket and packet-capture evidence remains required on the final assessment OS.

5. Contributions and sources

[REPLACE WITH EACH MEMBER'S CONTRIBUTION.] The coursework starter supplied the original structure and checksum guidance; the implementation was rewritten and checked against the coursework PDF. OpenAI Codex assisted with implementation, tests and notes. The team must review the code, rerun every claimed test, inspect captures and be able to explain matching, checksums, fixed deadlines and quoted ICMP packets.
