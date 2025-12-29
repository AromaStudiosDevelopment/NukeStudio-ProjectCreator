import logging
import os
import socket

try:  # Python 2 compatibility
    from urllib.parse import urlparse  # type: ignore
except ImportError:  # pragma: no cover - Python 2 fallback
    from urlparse import urlparse

import gazu

try:
    from requests.adapters import HTTPAdapter
except ImportError:  # pragma: no cover - requests should exist but guard defensively
    HTTPAdapter = None


def _looks_like_ip_host(host):
    """Best-effort check for IPv4/IPv6 literals."""
    if not host:
        return False
    host = host.strip("[]")
    try:
        socket.inet_aton(host)
        return True
    except OSError:
        pass
    if ":" in host:
        allowed = "0123456789abcdefABCDEF:."
        return all(char in allowed for char in host)
    return False


def _extract_host_from_url(url):
    """Return (hostname, netloc) tuple from a URL string."""
    if not url:
        return None, None
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        netloc = parsed.netloc or hostname
        if not hostname and netloc:
            hostname = netloc.split(":")[0]
        if hostname:
            hostname = hostname.split("@")[-1]
        if netloc:
            netloc = netloc.split("@")[-1]
        return hostname or None, netloc or None
    except Exception:  # pragma: no cover - defensive fallback
        return None, None


def _resolve_ca_bundle_path():
    """Expand the CA bundle path from env vars if present."""
    raw_path = os.environ.get("KITSU_CA_BUNDLE", "").strip()
    if not raw_path:
        return None
    expanded = os.path.expandvars(raw_path).strip('"')
    if os.path.isfile(expanded):
        return expanded
    logging.warning("KITSU_CA_BUNDLE set but file not found: %s", expanded)
    return None


class _IpHostnameAdapter(HTTPAdapter):  # type: ignore
    """Requests adapter that disables hostname checks for IP literals."""

    def __init__(self, ca_bundle):
        self._ca_bundle = ca_bundle
        HTTPAdapter.__init__(self)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):  # noqa: D401
        pool_kwargs.setdefault("assert_hostname", False)
        if self._ca_bundle:
            pool_kwargs.setdefault("ca_certs", self._ca_bundle)
        return HTTPAdapter.init_poolmanager(self, connections, maxsize, block=block, **pool_kwargs)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        proxy_kwargs.setdefault("assert_hostname", False)
        if self._ca_bundle:
            proxy_kwargs.setdefault("ca_certs", self._ca_bundle)
        return HTTPAdapter.proxy_manager_for(self, proxy, **proxy_kwargs)


def configure_kitsu_ca_bundle(expected_url=None):
    """Apply CA bundle and relaxed hostname rules for self-signed certificates."""
    ca_path = _resolve_ca_bundle_path()
    if not ca_path:
        return None

    os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_path)
    os.environ.setdefault("CURL_CA_BUNDLE", ca_path)

    if HTTPAdapter is None:
        return ca_path

    client_module = getattr(gazu, "client", None)
    raw_client = getattr(client_module, "default_client", None) if client_module else None
    session = getattr(raw_client, "session", None) if raw_client else None

    if session:
        session.verify = ca_path
        host, netloc = _extract_host_from_url(expected_url)
        if host and _looks_like_ip_host(host):
            try:
                adapter = _IpHostnameAdapter(ca_path)
                prefix_target = netloc or host
                session.mount("https://%s/" % prefix_target, adapter)
            except Exception as exc:  # pragma: no cover - defensive logging only
                logging.debug("Failed to mount IP hostname adapter for %s: %s", host, exc)

    logging.info("Configured Kitsu CA bundle: %s", ca_path)
    return ca_path