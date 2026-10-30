#!/usr/bin/env python3
"""A small IPv4 ICMP Echo client implemented with raw sockets.

The packet helpers in this module are intentionally reusable by Traceroute.py.
Importing this module never starts a ping session.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
import select
import socket
import struct
import time
from typing import Optional


ICMP_ECHO_REPLY = 0
ICMP_DEST_UNREACHABLE = 3
ICMP_ECHO_REQUEST = 8
ICMP_TIME_EXCEEDED = 11
ICMP_HEADER_SIZE = 8


@dataclass(frozen=True)
class IPv4Packet:
    source: str
    destination: str
    protocol: int
    ttl: int
    header_length: int
    payload: bytes


@dataclass(frozen=True)
class ICMPMessage:
    type: int
    code: int
    checksum: int
    identifier: int
    sequence: int
    payload: bytes


@dataclass(frozen=True)
class Probe:
    destination: str
    identifier: int
    sequence: int
    sent_at: float


@dataclass(frozen=True)
class ProbeReply:
    kind: str
    address: str
    elapsed: float
    icmp_type: int
    icmp_code: int


def checksum(data: bytes) -> int:
    """Return the RFC 1071 Internet checksum as a host-order integer."""
    if len(data) % 2:
        data += b"\x00"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def build_echo_request(identifier: int, sequence: int, payload: bytes) -> bytes:
    """Build one ICMP Echo Request, including its checksum."""
    if not 0 <= identifier <= 0xFFFF:
        raise ValueError("identifier must be between 0 and 65535")
    if not 0 <= sequence <= 0xFFFF:
        raise ValueError("sequence must be between 0 and 65535")
    header = struct.pack(
        "!BBHHH", ICMP_ECHO_REQUEST, 0, 0, identifier, sequence
    )
    packet_checksum = checksum(header + payload)
    return struct.pack(
        "!BBHHH", ICMP_ECHO_REQUEST, 0, packet_checksum, identifier, sequence
    ) + payload


def parse_ipv4_packet(packet: bytes) -> IPv4Packet:
    """Parse an IPv4 header using its IHL and retain the available payload.

    ICMP errors quote only the start of the original datagram, so the function
    deliberately permits fewer bytes than the original IPv4 total-length field.
    """
    if len(packet) < 20:
        raise ValueError("truncated IPv4 header")
    version_ihl = packet[0]
    version = version_ihl >> 4
    header_length = (version_ihl & 0x0F) * 4
    if version != 4:
        raise ValueError("packet is not IPv4")
    if header_length < 20 or len(packet) < header_length:
        raise ValueError("invalid or truncated IPv4 header length")
    fields = struct.unpack("!BBHHHBBH4s4s", packet[:20])
    return IPv4Packet(
        source=socket.inet_ntoa(fields[8]),
        destination=socket.inet_ntoa(fields[9]),
        protocol=fields[6],
        ttl=fields[5],
        header_length=header_length,
        payload=packet[header_length:],
    )


def parse_icmp_message(data: bytes) -> ICMPMessage:
    """Parse the common eight-byte ICMP header after checking its length."""
    if len(data) < ICMP_HEADER_SIZE:
        raise ValueError("truncated ICMP header")
    msg_type, code, msg_checksum, identifier, sequence = struct.unpack(
        "!BBHHH", data[:ICMP_HEADER_SIZE]
    )
    return ICMPMessage(
        type=msg_type,
        code=code,
        checksum=msg_checksum,
        identifier=identifier,
        sequence=sequence,
        payload=data[ICMP_HEADER_SIZE:],
    )


def quoted_echo_probe(message: ICMPMessage) -> Optional[tuple[str, int, int]]:
    """Extract destination, ID and sequence from an ICMP error quotation."""
    if message.type not in (ICMP_DEST_UNREACHABLE, ICMP_TIME_EXCEEDED):
        return None
    try:
        quoted_ip = parse_ipv4_packet(message.payload)
        if quoted_ip.protocol != socket.IPPROTO_ICMP:
            return None
        quoted_icmp = parse_icmp_message(quoted_ip.payload)
    except ValueError:
        return None
    if quoted_icmp.type != ICMP_ECHO_REQUEST or quoted_icmp.code != 0:
        return None
    return quoted_ip.destination, quoted_icmp.identifier, quoted_icmp.sequence


def parse_received_icmp(packet: bytes) -> ICMPMessage:
    """Accept raw-socket data with an IPv4 header or a bare ICMP message."""
    if packet and packet[0] >> 4 == 4:
        return parse_icmp_message(parse_ipv4_packet(packet).payload)
    return parse_icmp_message(packet)


def response_matches(message: ICMPMessage, probe: Probe, source: str) -> bool:
    """Return whether an Echo Reply or ICMP error belongs to *probe*."""
    if message.type == ICMP_ECHO_REPLY and message.code == 0:
        return (
            source == probe.destination
            and message.identifier == probe.identifier
            and message.sequence == probe.sequence
        )
    quoted = quoted_echo_probe(message)
    return quoted == (probe.destination, probe.identifier, probe.sequence)


def receive_matching_reply(
    icmp_socket: socket.socket, probe: Probe, deadline: float
) -> Optional[ProbeReply]:
    """Wait until a fixed deadline, ignoring unrelated and malformed packets."""
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            return None
        readable, _, _ = select.select([icmp_socket], [], [], remaining)
        if not readable:
            return None
        try:
            packet, sender = icmp_socket.recvfrom(65535)
            received_at = time.perf_counter()
            message = parse_received_icmp(packet)
        except (OSError, ValueError):
            continue
        source = sender[0]
        if not response_matches(message, probe, source):
            continue
        if message.type == ICMP_ECHO_REPLY:
            kind = "echo_reply"
        elif message.type == ICMP_TIME_EXCEEDED:
            kind = "time_exceeded"
        else:
            kind = "destination_unreachable"
        return ProbeReply(
            kind=kind,
            address=source,
            elapsed=received_at - probe.sent_at,
            icmp_type=message.type,
            icmp_code=message.code,
        )


def send_probe(
    icmp_socket: socket.socket,
    destination: str,
    identifier: int,
    sequence: int,
    payload: bytes,
) -> Probe:
    packet = build_echo_request(identifier, sequence, payload)
    sent_at = time.perf_counter()
    icmp_socket.sendto(packet, (destination, 0))
    return Probe(destination, identifier, sequence, sent_at)


def ping(
    destination: str,
    count: Optional[int] = None,
    timeout: float = 1.0,
    interval: float = 1.0,
) -> int:
    """Ping a destination until Ctrl+C or until *count* probes are sent."""
    try:
        destination_ip = socket.gethostbyname(destination)
    except socket.gaierror as exc:
        print(f"ping: cannot resolve {destination!r}: {exc}")
        return 2

    identifier = os.getpid() & 0xFFFF
    sent = 0
    received = 0
    rtts: list[float] = []
    print(f"PING {destination} ({destination_ip}) with 56 data bytes")

    try:
        with socket.socket(
            socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP
        ) as icmp_socket:
            while count is None or sent < count:
                sequence = sent & 0xFFFF
                payload = struct.pack("!d", time.time()) + bytes(
                    (index & 0xFF for index in range(48))
                )
                try:
                    probe = send_probe(
                        icmp_socket, destination_ip, identifier, sequence, payload
                    )
                except OSError as exc:
                    print(f"send failed for seq={sequence}: {exc}")
                    return 2
                sent += 1
                reply = receive_matching_reply(
                    icmp_socket, probe, probe.sent_at + timeout
                )
                if reply is None:
                    print(f"Request timeout for icmp_seq={sequence}")
                elif reply.kind == "echo_reply":
                    elapsed_ms = reply.elapsed * 1000
                    received += 1
                    rtts.append(elapsed_ms)
                    print(
                        f"64 bytes from {reply.address}: icmp_seq={sequence} "
                        f"time={elapsed_ms:.3f} ms"
                    )
                else:
                    print(
                        f"From {reply.address}: icmp_seq={sequence} "
                        f"{reply.kind.replace('_', ' ')} "
                        f"(type={reply.icmp_type}, code={reply.icmp_code})"
                    )
                if count is None or sent < count:
                    time.sleep(max(0.0, interval - (time.perf_counter() - probe.sent_at)))
    except PermissionError:
        print(
            "ping: raw ICMP socket permission denied; run with the privileges "
            "required by your operating system"
        )
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted")

    loss = ((sent - received) / sent * 100) if sent else 0.0
    print(f"\n--- {destination} ping statistics ---")
    print(f"{sent} packets transmitted, {received} received, {loss:.1f}% packet loss")
    if rtts:
        print(
            "round-trip min/avg/max = "
            f"{min(rtts):.3f}/{sum(rtts) / len(rtts):.3f}/{max(rtts):.3f} ms"
        )
    else:
        print("no RTT samples")
    return 0 if received else 1


def positive_int(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return result


def positive_float(value: str) -> float:
    result = float(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send IPv4 ICMP Echo Requests")
    parser.add_argument("destination", help="IPv4 address or hostname")
    parser.add_argument("-c", "--count", type=positive_int, default=None)
    parser.add_argument("-W", "--timeout", type=positive_float, default=1.0)
    parser.add_argument("-i", "--interval", type=positive_float, default=1.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return ping(args.destination, args.count, args.timeout, args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
