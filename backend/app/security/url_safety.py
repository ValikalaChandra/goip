from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::/128"),
]

BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata.google.internal.",
}


class UnsafeURL(ValueError):
    pass


@dataclass
class CheckedURL:
    url: str
    host: str
    ips: list[str]


def _blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return True
    return any(ip in network for network in BLOCKED_NETWORKS)


def check_url(url: str, *, resolve=socket.getaddrinfo) -> CheckedURL:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeURL("Only http and https URLs are allowed")
    if parsed.username or parsed.password:
        raise UnsafeURL("URLs with embedded credentials are rejected")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host or host in BLOCKED_HOSTS or host.endswith(".local") or host.endswith(".internal"):
        raise UnsafeURL("Host is not a public destination")
    if host.replace(".", "").isdigit() and host.count(".") != 3:
        raise UnsafeURL("Numeric host forms are rejected")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    ips: list[str] = []
    if ip is not None:
        if _blocked_ip(ip):
            raise UnsafeURL("IP address is not a public destination")
        ips = [str(ip)]
    else:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            infos = resolve(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise UnsafeURL("Host did not resolve") from exc
        for info in infos:
            address = info[4][0]
            parsed_ip = ipaddress.ip_address(address)
            if _blocked_ip(parsed_ip):
                raise UnsafeURL("Host resolves to a non-public address")
            ips.append(str(parsed_ip))
    if not ips:
        raise UnsafeURL("Host did not resolve")
    return CheckedURL(url=url, host=host, ips=ips)


async def fetch_public(url: str, *, timeout: float = 20.0, max_redirects: int = 3) -> httpx.Response:
    current = url
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(max_redirects + 1):
            checked = check_url(current)
            response = await client.get(
                checked.url,
                headers={"User-Agent": "GOIP/0.1 (+local research; public pages only)"},
            )
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise UnsafeURL("Redirect missing location")
                current = urljoin(str(response.url), location)
                continue
            return response
    raise UnsafeURL("Too many redirects")
