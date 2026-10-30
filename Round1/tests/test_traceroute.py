import contextlib
import io
import unittest
from unittest import mock

import ICMPPing
import Traceroute


class FakeRawSocket:
    def __init__(self):
        self.ttls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def setsockopt(self, _level, _option, ttl):
        self.ttls.append(ttl)


class TracerouteFlowTests(unittest.TestCase):
    def test_ttl_increases_and_matching_echo_stops_trace(self):
        raw_socket = FakeRawSocket()

        def fake_send(_socket, destination, identifier, sequence, _payload):
            return ICMPPing.Probe(destination, identifier, sequence, 10.0)

        def fake_receive(_socket, probe, _deadline):
            if probe.sequence < 2:
                return ICMPPing.ProbeReply(
                    "time_exceeded", "192.0.2.1", 0.01, 11, 0
                )
            return ICMPPing.ProbeReply(
                "echo_reply", "198.51.100.2", 0.02, 0, 0
            )

        with mock.patch.object(Traceroute.socket, "gethostbyname", return_value="198.51.100.2"), mock.patch.object(
            Traceroute.socket, "socket", return_value=raw_socket
        ), mock.patch.object(Traceroute, "send_probe", side_effect=fake_send), mock.patch.object(
            Traceroute, "receive_matching_reply", side_effect=fake_receive
        ), contextlib.redirect_stdout(io.StringIO()) as output:
            result = Traceroute.traceroute(
                "example.test", max_hops=5, timeout=1, probes_per_hop=2
            )

        self.assertEqual(result, 0)
        self.assertEqual(raw_socket.ttls, [1, 2])
        self.assertIn("Destination reached", output.getvalue())

    def test_silent_hops_continue_until_maximum(self):
        raw_socket = FakeRawSocket()
        with mock.patch.object(Traceroute.socket, "gethostbyname", return_value="198.51.100.2"), mock.patch.object(
            Traceroute.socket, "socket", return_value=raw_socket
        ), mock.patch.object(
            Traceroute,
            "send_probe",
            side_effect=lambda _s, destination, identifier, sequence, _p: ICMPPing.Probe(
                destination, identifier, sequence, 10.0
            ),
        ), mock.patch.object(
            Traceroute, "receive_matching_reply", return_value=None
        ), contextlib.redirect_stdout(io.StringIO()) as output:
            result = Traceroute.traceroute(
                "example.test", max_hops=3, timeout=1, probes_per_hop=1
            )

        self.assertEqual(result, 1)
        self.assertEqual(raw_socket.ttls, [1, 2, 3])
        self.assertEqual(output.getvalue().count("  *"), 3)
        self.assertIn("not reached within 3 hops", output.getvalue())


if __name__ == "__main__":
    unittest.main()
