import socket
import struct
import unittest
from unittest import mock

import ICMPPing as ping


def ipv4_packet(payload, source="192.0.2.1", destination="198.51.100.2", ihl=5):
    options = b"\x01\x01\x01\x01" * (ihl - 5)
    header = struct.pack(
        "!BBHHHBBH4s4s",
        (4 << 4) | ihl,
        0,
        ihl * 4 + len(payload),
        1,
        0,
        64,
        socket.IPPROTO_ICMP,
        0,
        socket.inet_aton(source),
        socket.inet_aton(destination),
    )
    return header + options + payload


class ICMPPacketTests(unittest.TestCase):
    def test_echo_request_has_valid_checksum_and_fields(self):
        packet = ping.build_echo_request(0x1234, 7, b"payload")
        message = ping.parse_icmp_message(packet)
        self.assertEqual((message.type, message.code), (8, 0))
        self.assertEqual((message.identifier, message.sequence), (0x1234, 7))
        self.assertEqual(ping.checksum(packet), 0)

    def test_ipv4_parser_uses_ihl_instead_of_assuming_twenty_bytes(self):
        raw = ipv4_packet(b"icmp-data", ihl=6)
        parsed = ping.parse_ipv4_packet(raw)
        self.assertEqual(parsed.header_length, 24)
        self.assertEqual(parsed.payload, b"icmp-data")

    def test_truncated_packets_are_rejected(self):
        with self.assertRaises(ValueError):
            ping.parse_ipv4_packet(b"short")
        with self.assertRaises(ValueError):
            ping.parse_icmp_message(b"short")

    def test_echo_reply_requires_source_id_and_sequence(self):
        probe = ping.Probe("198.51.100.2", 55, 9, 1.0)
        reply = ping.parse_icmp_message(struct.pack("!BBHHH", 0, 0, 0, 55, 9))
        self.assertTrue(ping.response_matches(reply, probe, "198.51.100.2"))
        self.assertFalse(ping.response_matches(reply, probe, "198.51.100.3"))
        wrong_sequence = ping.parse_icmp_message(
            struct.pack("!BBHHH", 0, 0, 0, 55, 10)
        )
        self.assertFalse(
            ping.response_matches(wrong_sequence, probe, "198.51.100.2")
        )

    def test_time_exceeded_matches_quoted_original_probe(self):
        request = ping.build_echo_request(55, 9, b"payload")
        quoted = ipv4_packet(request, destination="198.51.100.2")
        outer = ping.parse_icmp_message(struct.pack("!BBHHH", 11, 0, 0, 0, 0) + quoted)
        probe = ping.Probe("198.51.100.2", 55, 9, 1.0)
        self.assertTrue(ping.response_matches(outer, probe, "203.0.113.1"))

        wrong_request = ping.build_echo_request(55, 10, b"payload")
        wrong_outer = ping.parse_icmp_message(
            struct.pack("!BBHHH", 11, 0, 0, 55, 9)
            + ipv4_packet(wrong_request, destination="198.51.100.2")
        )
        self.assertFalse(ping.response_matches(wrong_outer, probe, "203.0.113.1"))

    def test_destination_unreachable_uses_quoted_probe(self):
        request = ping.build_echo_request(1, 2, b"")
        error = ping.parse_icmp_message(
            struct.pack("!BBHHH", 3, 1, 0, 999, 999)
            + ipv4_packet(request, destination="198.51.100.2")
        )
        probe = ping.Probe("198.51.100.2", 1, 2, 1.0)
        self.assertTrue(ping.response_matches(error, probe, "203.0.113.5"))

    def test_unrelated_packet_does_not_restart_timeout(self):
        class FakeSocket:
            def recvfrom(self, _size):
                unrelated = struct.pack("!BBHHH", 0, 0, 0, 10, 99)
                return unrelated, ("198.51.100.2", 0)

        probe = ping.Probe("198.51.100.2", 10, 8, 9.0)
        with mock.patch.object(
            ping.time, "perf_counter", side_effect=[9.1, 9.2, 9.3]
        ), mock.patch.object(
            ping.select, "select", side_effect=[([FakeSocket()], [], []), ([], [], [])]
        ) as selected:
            result = ping.receive_matching_reply(FakeSocket(), probe, 10.0)
        self.assertIsNone(result)
        self.assertAlmostEqual(selected.call_args_list[0].args[3], 0.9)
        self.assertAlmostEqual(selected.call_args_list[1].args[3], 0.7)


if __name__ == "__main__":
    unittest.main()
