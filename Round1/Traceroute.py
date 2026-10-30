#!/usr/bin/env python3
"""ICMP traceroute built on the packet helpers in ICMPPing.py."""

from __future__ import annotations

import argparse
import os
import socket
import struct
import time

from ICMPPing import (
    positive_float,
    positive_int,
    receive_matching_reply,
    send_probe,
)


def display_address(address: str, resolve_names: bool) -> str:
    if not resolve_names:
        return address
    try:
        return f"{socket.gethostbyaddr(address)[0]} ({address})"
    except socket.herror:
        return address


def traceroute(
    destination: str,
    max_hops: int = 30,
    timeout: float = 1.0,
    probes_per_hop: int = 3,
    resolve_names: bool = False,
) -> int:
    try:
        destination_ip = socket.gethostbyname(destination)
    except socket.gaierror as exc:
        print(f"traceroute: cannot resolve {destination!r}: {exc}")
        return 2

    identifier = os.getpid() & 0xFFFF
    print(
        f"traceroute to {destination} ({destination_ip}), "
        f"{max_hops} hops max, {probes_per_hop} probes per hop"
    )

    try:
        with socket.socket(
            socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP
        ) as icmp_socket:
            for ttl in range(1, max_hops + 1):
                icmp_socket.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, ttl)
                results: list[str] = []
                reached_destination = False
                terminal_error = False

                for probe_index in range(probes_per_hop):
                    sequence = ((ttl - 1) * probes_per_hop + probe_index) & 0xFFFF
                    payload = struct.pack("!dI", time.time(), sequence) + b"CNSCC231"
                    try:
                        probe = send_probe(
                            icmp_socket,
                            destination_ip,
                            identifier,
                            sequence,
                            payload,
                        )
                    except OSError as exc:
                        results.append(f"send error: {exc}")
                        continue
                    reply = receive_matching_reply(
                        icmp_socket, probe, probe.sent_at + timeout
                    )
                    if reply is None:
                        results.append("*")
                        continue

                    address = display_address(reply.address, resolve_names)
                    suffix = ""
                    if reply.kind == "destination_unreachable":
                        suffix = f" !U({reply.icmp_code})"
                        terminal_error = True
                    elif reply.kind == "echo_reply":
                        reached_destination = True
                    results.append(f"{address} {reply.elapsed * 1000:.3f} ms{suffix}")

                print(f"{ttl:2d}  " + "    ".join(results))
                if reached_destination:
                    print("Destination reached by a matching Echo Reply.")
                    return 0
                if terminal_error:
                    print("Trace stopped after a matching Destination Unreachable.")
                    return 1
    except PermissionError:
        print(
            "traceroute: raw ICMP socket permission denied; run with the "
            "privileges required by your operating system"
        )
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 130

    print(f"Destination was not reached within {max_hops} hops.")
    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trace an IPv4 route with ICMP")
    parser.add_argument("destination", help="IPv4 address or hostname")
    parser.add_argument("-m", "--max-hops", type=positive_int, default=30)
    parser.add_argument("-W", "--timeout", type=positive_float, default=1.0)
    parser.add_argument("-q", "--probes", type=positive_int, default=3)
    parser.add_argument(
        "-n",
        "--resolve-names",
        action="store_true",
        help="perform reverse DNS lookups (may make output slower)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return traceroute(
        args.destination,
        max_hops=args.max_hops,
        timeout=args.timeout,
        probes_per_hop=args.probes,
        resolve_names=args.resolve_names,
    )


if __name__ == "__main__":
    raise SystemExit(main())
