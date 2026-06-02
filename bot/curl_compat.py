"""
Compatibility wrapper: makes curl_cffi's AsyncSession look like aiohttp.ClientSession
so shopify_native.py can use Chrome TLS fingerprinting with zero API changes.

Key differences bridged:
  - resp.status_code  →  resp.status
  - resp.json()       →  await resp.json(content_type=None)
  - resp.text         →  await resp.text()
  - aiohttp.ClientTimeout(total=N)  →  just N (int)
  - Per-request context managers (async with session.get(...) as r:)
"""

import logging
logger = logging.getLogger(__name__)


class _CurlResponse:
    """Wraps a curl_cffi response to look like an aiohttp response."""

    def __init__(self, resp):
        self._r = resp

    @property
    def status(self):
        return self._r.status_code

    @property
    def url(self):
        return str(self._r.url)

    @property
    def headers(self):
        return self._r.headers

    async def json(self, content_type=None):
        return self._r.json()

    async def text(self):
        return self._r.text

    async def read(self):
        return self._r.content


class _CurlRequest:
    """Async context manager for a single curl_cffi request."""

    def __init__(self, coro):
        self._coro = coro
        self._resp = None

    async def __aenter__(self):
        resp = await self._coro
        self._resp = _CurlResponse(resp)
        return self._resp

    async def __aexit__(self, *args):
        pass


def _extract_timeout(kwargs, default=30):
    """Pop 'timeout' from kwargs; convert aiohttp.ClientTimeout → float."""
    t = kwargs.pop("timeout", default)
    if hasattr(t, "total"):
        return t.total or default
    return t or default


def _clean_kwargs(kwargs):
    """Remove aiohttp-specific kwargs that curl_cffi doesn't understand."""
    kwargs.pop("connector", None)
    return kwargs


class ChromeSession:
    """
    Drop-in replacement for aiohttp.ClientSession that uses curl_cffi
    with Chrome 131 TLS impersonation to bypass Shopify bot detection.

    Usage (identical to aiohttp):
        async with ChromeSession(timeout=aiohttp.ClientTimeout(total=90)) as session:
            async with session.get(url, headers=headers, timeout=...) as resp:
                data = await resp.json(content_type=None)
    """

    def __init__(self, timeout=None, connector=None, **kwargs):
        self._default_timeout = 30
        if timeout is not None:
            if hasattr(timeout, "total"):
                self._default_timeout = timeout.total or 30
            else:
                self._default_timeout = timeout
        self._session = None

    async def __aenter__(self):
        try:
            from curl_cffi.requests import AsyncSession
            self._session = AsyncSession(impersonate="chrome131", verify=False)
            logger.debug("ChromeSession: using curl_cffi chrome131 fingerprint")
        except Exception as e:
            import aiohttp
            logger.warning(f"curl_cffi unavailable ({e}), falling back to aiohttp")
            self._session = None
            self._aiohttp_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._default_timeout),
                connector=aiohttp.TCPConnector(ssl=False),
            )
            self._use_aiohttp = True
            await self._aiohttp_session.__aenter__()
            return self._aiohttp_session
        self._use_aiohttp = False
        return self

    async def __aexit__(self, *args):
        if self._use_aiohttp:
            await self._aiohttp_session.__aexit__(*args)
        elif self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass

    def get(self, url, **kwargs):
        if self._use_aiohttp:
            return self._aiohttp_session.get(url, **kwargs)
        timeout = _extract_timeout(kwargs, self._default_timeout)
        _clean_kwargs(kwargs)
        return _CurlRequest(self._session.get(url, timeout=timeout, **kwargs))

    def post(self, url, **kwargs):
        if self._use_aiohttp:
            return self._aiohttp_session.post(url, **kwargs)
        timeout = _extract_timeout(kwargs, self._default_timeout)
        _clean_kwargs(kwargs)
        return _CurlRequest(self._session.post(url, timeout=timeout, **kwargs))
