import json
import subprocess
import unittest
from unittest.mock import patch

from puda.host_addresses import (
    HostAddresses,
    _fallback_lan_ipv4,
    _local_ipv4,
    _parse_tailscale_status,
    _skip_iface,
    _tailscale_addresses,
    discover_host_addresses,
)


class ParseTailscaleStatusTests(unittest.TestCase):
    def test_reads_ipv4_and_strips_trailing_dot(self):
        ipv4, dns = _parse_tailscale_status(
            {
                "Self": {
                    "TailscaleIPs": ["100.99.243.61", "fd7a:115c:a1e0::1"],
                    "DNSName": "host.tailnet.ts.net.",
                }
            }
        )
        self.assertEqual(ipv4, "100.99.243.61")
        self.assertEqual(dns, "host.tailnet.ts.net")

    def test_missing_or_invalid_self_returns_none(self):
        self.assertEqual(_parse_tailscale_status({}), (None, None))
        self.assertEqual(_parse_tailscale_status({"Self": []}), (None, None))
        self.assertEqual(_parse_tailscale_status(None), (None, None))


class SkipIfaceTests(unittest.TestCase):
    def test_skips_virtual_and_tailscale_interfaces(self):
        for name in ("lo", "tailscale0", "docker0", "br-abc", "veth123", "tun0"):
            self.assertTrue(_skip_iface(name), name)

    def test_keeps_physical_interfaces(self):
        for name in ("enp1s0", "eth0", "wlo1", "wlan0"):
            self.assertFalse(_skip_iface(name), name)


class LocalIpTests(unittest.TestCase):
    def test_uses_default_route_when_it_is_lan(self):
        with patch("puda.host_addresses._default_route_ipv4", return_value="192.168.1.10"):
            self.assertEqual(_local_ipv4(), "192.168.1.10")

    def test_falls_back_when_default_route_is_cgnat(self):
        with (
            patch("puda.host_addresses._default_route_ipv4", return_value="100.99.243.61"),
            patch(
                "puda.host_addresses._interface_ipv4s",
                return_value=[("tailscale0", "100.99.243.61"), ("wlo1", "172.31.8.193")],
            ),
        ):
            self.assertEqual(_local_ipv4(), "172.31.8.193")

    def test_fallback_skips_cgnat_and_loopback(self):
        with patch(
            "puda.host_addresses._interface_ipv4s",
            return_value=[("wlo1", "100.64.1.1"), ("enp1s0", "10.0.0.5")],
        ):
            self.assertEqual(_fallback_lan_ipv4(), "10.0.0.5")


class DiscoverHostAddressesTests(unittest.TestCase):
    def test_omits_local_ip_when_it_duplicates_tailscale(self):
        with (
            patch("puda.host_addresses._tailscale_addresses", return_value=("100.1.2.3", "host.ts.net")),
            patch("puda.host_addresses._local_ipv4", return_value="100.1.2.3"),
        ):
            addresses = discover_host_addresses()
        self.assertEqual(
            addresses,
            HostAddresses(local_ip=None, tailscale_ip="100.1.2.3", magicdns="host.ts.net"),
        )

    def test_returns_all_fields(self):
        with (
            patch("puda.host_addresses._tailscale_addresses", return_value=("100.1.2.3", "host.ts.net")),
            patch("puda.host_addresses._local_ipv4", return_value="192.168.1.10"),
        ):
            addresses = discover_host_addresses()
        self.assertEqual(
            addresses,
            HostAddresses(local_ip="192.168.1.10", tailscale_ip="100.1.2.3", magicdns="host.ts.net"),
        )

    def test_survives_discovery_errors(self):
        with patch("puda.host_addresses._tailscale_addresses", side_effect=RuntimeError("boom")):
            self.assertEqual(discover_host_addresses(), HostAddresses())

    def test_tailscale_cli_missing_returns_none(self):
        with patch("puda.host_addresses.subprocess.run", side_effect=FileNotFoundError):
            self.assertEqual(_tailscale_addresses(), (None, None))

    def test_tailscale_timeout_returns_none(self):
        with patch(
            "puda.host_addresses.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="tailscale", timeout=1),
        ):
            self.assertEqual(_tailscale_addresses(), (None, None))

    def test_tailscale_parses_json_stdout(self):
        completed = subprocess.CompletedProcess(
            args=["tailscale", "status", "--json"],
            returncode=0,
            stdout=json.dumps(
                {"Self": {"TailscaleIPs": ["100.1.2.3"], "DNSName": "host.ts.net."}}
            ),
            stderr="",
        )
        with patch("puda.host_addresses.subprocess.run", return_value=completed):
            self.assertEqual(_tailscale_addresses(), ("100.1.2.3", "host.ts.net"))


if __name__ == "__main__":
    unittest.main()
