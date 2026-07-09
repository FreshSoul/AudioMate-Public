from __future__ import annotations

import ipaddress
import json
import re
import socket
from html import unescape
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup


class WebAccessError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# SSRF guard
#
# ``fetch_webpage`` is exposed to generated code via
# ``call_structured_tool``/``fetch_webpage(...)``. Without this guard a
# prompt-injection (or a careless skill) could ask the agent to fetch
# ``http://127.0.0.1:1234/`` or the cloud metadata endpoint
# (``http://169.254.169.254/``) and leak the response — internal services
# on the user's machine and inside the network are otherwise reachable.
#
# We block by IP address category (loopback, private, link-local, multicast,
# reserved) AND by a few well-known sensitive hostnames. The check happens
# AFTER hostname → IP resolution so an attacker can't sneak through a DNS
# record that resolves to a private address.
# ---------------------------------------------------------------------------

_BLOCKED_HOSTNAMES = frozenset({
    "localhost", "localhost.localdomain", "metadata.google.internal",
})


def _hostname_is_private(hostname: str) -> tuple[bool, str]:
    """Return ``(blocked, reason)``.

    ``blocked=True`` if the hostname resolves to any non-globally-routable
    address. Resolution failures are treated as "let the OS decide" (we let
    ``urlopen`` fail naturally with a meaningful error).
    """
    host = (hostname or "").strip().strip("[]").lower()
    if not host:
        return True, "missing host"
    if host in _BLOCKED_HOSTNAMES:
        return True, f"blocked hostname: {host}"

    # Try resolving every address record. If ANY resolves to a non-global
    # address we refuse — pinning to "first answer is public" lets an
    # attacker rebind DNS between check and connect.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False, ""  # let the underlying urlopen surface the error

    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        # ``is_global`` is the authoritative "publicly routable" predicate.
        # It already excludes loopback, link-local, private (10/8, 172.16/12,
        # 192.168/16), multicast, reserved, unspecified.
        if not ip.is_global:
            return True, f"non-public address: {ip_str}"
    return False, ""


class WebAccessService:
    USER_AGENT = "AudioMate/1.0"
    MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024

    def fetch_webpage(self, url: str, max_chars: int = 12000, timeout: int = 15) -> dict:
        normalized_url = (url or "").strip()
        if not normalized_url:
            raise WebAccessError("url is required")

        parsed = urlparse(normalized_url)
        if parsed.scheme not in {"http", "https"}:
            raise WebAccessError("Only http and https URLs are supported")

        blocked, reason = _hostname_is_private(parsed.hostname or "")
        if blocked:
            raise WebAccessError(
                f"URL refused for safety: {reason}. AudioMate does not fetch "
                "loopback, private-network, or cloud-metadata endpoints."
            )

        request = Request(
            normalized_url,
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept": "text/html,application/json,text/plain;q=0.9,*/*;q=0.8",
            },
        )

        with urlopen(request, timeout=max(1, int(timeout or 15))) as response:
            final_url = response.geturl()
            # urlopen follows redirects transparently; re-validate the final
            # URL so an attacker can't 302 us into a private endpoint.
            final_parsed = urlparse(final_url)
            if final_parsed.scheme in {"http", "https"}:
                blocked, reason = _hostname_is_private(final_parsed.hostname or "")
                if blocked:
                    raise WebAccessError(
                        f"Redirect target refused for safety: {reason}."
                    )
            content_type = response.headers.get_content_type() or "application/octet-stream"
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read(self.MAX_DOWNLOAD_BYTES)

        text = raw.decode(charset, errors="replace")
        if content_type == "application/json":
            return self._build_json_result(final_url, content_type, text, max_chars)
        if "html" in content_type:
            return self._build_html_result(final_url, content_type, text, max_chars)
        return self._build_text_result(final_url, content_type, text, max_chars)

    def _normalize_text(self, value: str, max_chars: int) -> str:
        compact = re.sub(r"\s+", " ", unescape(value or "")).strip()
        return compact[: max(200, int(max_chars or 12000))]

    def _build_json_result(self, url: str, content_type: str, text: str, max_chars: int) -> dict:
        try:
            parsed = json.loads(text)
            pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
        except Exception:
            pretty = text
        return {
            "url": url,
            "content_type": content_type,
            "title": "",
            "text": pretty[: max(200, int(max_chars or 12000))],
            "links": [],
        }

    def _build_text_result(self, url: str, content_type: str, text: str, max_chars: int) -> dict:
        return {
            "url": url,
            "content_type": content_type,
            "title": "",
            "text": self._normalize_text(text, max_chars),
            "links": [],
        }

    def _build_html_result(self, url: str, content_type: str, html: str, max_chars: int) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        title = ""
        if soup.title and soup.title.string:
            title = self._normalize_text(soup.title.string, 300)

        text = self._normalize_text(soup.get_text(" ", strip=True), max_chars)

        links = []
        seen = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(url, anchor.get("href") or "")
            if href in seen or urlparse(href).scheme not in {"http", "https"}:
                continue
            seen.add(href)
            links.append(
                {
                    "text": self._normalize_text(anchor.get_text(" ", strip=True), 120),
                    "url": href,
                }
            )
            if len(links) >= 20:
                break

        return {
            "url": url,
            "content_type": content_type,
            "title": title,
            "text": text,
            "links": links,
        }
