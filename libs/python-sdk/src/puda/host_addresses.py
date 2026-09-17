"""Discover the edge host's LAN IPv4, Tailscale IPv4, and MagicDNS name."""
from __future__ import annotations

import ipaddress
import json
import logging
import socket
import subprocess
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_RFC1918 = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
_SKIP_IFACE_PREFIXES = (
    "lo",
    "docker",
    "br-",
    "veth",
    "cni",
    "flannel",
    "virbr",
    "tun",
    "wg",
    "tailscale",
    "vmnet",
    "vboxnet",
)
_TAILSCALE_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True)
class HostAddresses:
    local_ip: str | None = None
    tailscale_ip: str | None = None
    magicdns: str | None = None


def discover_host_addresses() -> HostAddresses:
    """Best-effort local + Tailscale addresses. Never raises."""
    try:
        tailscale_ip, magicdns = _tailscale_addresses()
        local_ip = _local_ipv4()
        if local_ip and local_ip == tailscale_ip:
            local_ip = None
        return HostAddresses(
            local_ip=local_ip,
            tailscale_ip=tailscale_ip,
            magicdns=magicdns,
        )
    except Exception:
        logger.debug("Host address discovery failed", exc_info=True)
        return HostAddresses()


def _is_cgnat(addr: ipaddress.IPv4Address) -> bool:
    return addr in _CGNAT


def _is_rfc1918(addr: ipaddress.IPv4Address) -> bool:
    return any(addr in network for network in _RFC1918)


def _parse_ipv4(value: str) -> ipaddress.IPv4Address | None:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return None
    if not isinstance(addr, ipaddress.IPv4Address):
        return None
    return addr


def _skip_iface(name: str) -> bool:
    lowered = name.lower()
    return any(lowered.startswith(prefix) for prefix in _SKIP_IFACE_PREFIXES)


def _parse_tailscale_status(data: Any) -> tuple[str | None, str | None]:
    if not isinstance(data, dict):
        return None, None
    self_info = data.get("Self")
    if not isinstance(self_info, dict):
        return None, None
    ipv4 = None
    ips = self_info.get("TailscaleIPs")
    if isinstance(ips, list):
        for ip in ips:
            if isinstance(ip, str) and _parse_ipv4(ip) is not None:
                ipv4 = ip
                break
    dns = self_info.get("DNSName")
    if isinstance(dns, str):
        dns = dns.strip().rstrip(".") or None
    else:
        dns = None
    return ipv4, dns


def _tailscale_addresses() -> tuple[str | None, str | None]:
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=_TAILSCALE_TIMEOUT_SECONDS,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None, None
    if result.returncode != 0:
        return None, None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, None
    return _parse_tailscale_status(payload)


def _default_route_ipv4() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("1.1.1.1", 80))
            return sock.getsockname()[0]
    except OSError:
        return None


def _interface_ipv4s() -> list[tuple[str, str]]:
    try:
        import fcntl
        import struct
    except ImportError:
        return []
    results: list[tuple[str, str]] = []
    try:
        names = socket.if_nameindex()
    except OSError:
        return []
    for _index, name in names:
        if _skip_iface(name):
            continue
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            packed = struct.pack("256s", name.encode()[:15])
            raw = fcntl.ioctl(sock.fileno(), 0x8915, packed)
            ip = socket.inet_ntoa(raw[20:24])
        except OSError:
            continue
        finally:
            sock.close()
        results.append((name, ip))
    return results


def _fallback_lan_ipv4() -> str | None:
    for _name, ip in _interface_ipv4s():
        addr = _parse_ipv4(ip)
        if addr is None:
            continue
        if addr.is_loopback or addr.is_link_local or _is_cgnat(addr):
            continue
        if _is_rfc1918(addr):
            return ip
    return None


def _local_ipv4() -> str | None:
    candidate = _default_route_ipv4()
    addr = _parse_ipv4(candidate) if candidate else None
    if addr is not None and not addr.is_loopback and not addr.is_link_local and not _is_cgnat(addr):
        return str(addr)
    return _fallback_lan_ipv4()
