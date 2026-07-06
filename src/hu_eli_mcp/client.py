"""Async httpx client for Nemzeti Jogszabalytar (njt.jog.gov.hu), with cache.

NJT (njt.jog.gov.hu) has no REST/JSON API. It is an AngularJS SPA whose search/browse UI
requires a session and JavaScript (not usable headlessly), but whose native ELI URIs
(``/eli/{tip}/{ev}[/{kib}]/{sr}...``, documented at ``/eli/urisemak``) are plain HTTP redirects
(302) to a server-rendered ``/jogszabaly/{doc_id}`` HTML page - reachable with no JavaScript and
no cookies. This client resolves an ELI URI, detects the "not found" case (NJT redirects an
unresolvable ELI to its search-assist page ``/eli/kereses`` instead of a 404), and fetches the
resulting document page or code-list page.

``robots.txt`` explicitly ``Allow``s ``/jogszabaly/*`` and does not mention ``/eli/*``
(no ``Disallow`` covers it); only ``/search/*`` is disallowed, which this client never calls.
"""

from __future__ import annotations

import anyio
import httpx

from .cache import HttpCache

DEFAULT_BASE_URL = "https://njt.jog.gov.hu"
NOT_FOUND_REDIRECT_PATH = "/eli/kereses"
DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
USER_AGENT = "hu-eli-mcp/0.1.0 (+https://github.com/matematicsolutions/hu-eli-mcp)"

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3


class HuError(Exception):
    """Raised when an NJT page cannot be retrieved or is invalid."""


class HuNotFoundError(HuError):
    """Raised when NJT redirects an ELI URI to its search-assist page (unresolvable ELI)."""


class NjtClient:
    """Async client for njt.jog.gov.hu. Use as ``async with NjtClient() as c: ...``."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        cache: HttpCache | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._cache = cache or HttpCache()
        self._http = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
            },
            follow_redirects=False,
        )

    async def __aenter__(self) -> NjtClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()
        self._cache.close()

    async def _get_no_redirect(self, url: str) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return await self._http.get(url)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt == _MAX_ATTEMPTS - 1:
                    raise
            await anyio.sleep(0.5 * (2**attempt))
        assert last_exc is not None
        raise last_exc

    async def _get_cached(self, url: str, *, category: str) -> str:
        cached = self._cache.get(url)
        if cached is not None and isinstance(cached, str):
            return cached
        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = await self._http.get(url, follow_redirects=True)
                resp.raise_for_status()
                self._cache.set(url, resp.text, ttl=HttpCache.ttl_for(category))
                return resp.text
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code == 404:
                    raise HuNotFoundError(f"NJT returned 404 for {url!r}.") from exc
                if exc.response.status_code not in _RETRY_STATUS or attempt == _MAX_ATTEMPTS - 1:
                    raise
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt == _MAX_ATTEMPTS - 1:
                    raise
            await anyio.sleep(0.5 * (2**attempt))
        assert last_exc is not None
        raise last_exc

    async def resolve_eli(self, eli_path: str) -> tuple[str, str]:
        """Resolve an ELI path (e.g. ``/eli/TV/2013/5``) to its document page.

        Returns ``(source_url, html)``. Raises ``HuNotFoundError`` if NJT redirects the ELI to
        its search-assist page (the documented behaviour for an unresolvable ELI), or if the
        document page itself 404s.
        """
        eli_url = f"{self.base_url}{eli_path}"
        cache_key = f"resolve:{eli_url}"
        cached = self._cache.get(cache_key)
        if cached is not None and isinstance(cached, dict):
            return cached["source_url"], cached["html"]

        resp = await self._get_no_redirect(eli_url)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location", "")
            if NOT_FOUND_REDIRECT_PATH in location:
                raise HuNotFoundError(
                    f"NJT could not resolve ELI {eli_path!r} (redirected to search-assist)."
                )
            source_url = location if location.startswith("http") else f"{self.base_url}{location}"
        elif resp.status_code == 200:
            source_url = eli_url
        elif resp.status_code == 404:
            raise HuNotFoundError(f"NJT returned 404 for ELI {eli_path!r}.")
        else:
            resp.raise_for_status()
            source_url = eli_url

        html = await self._get_cached(source_url, category="act")
        cache_value = {"source_url": source_url, "html": html}
        self._cache.set(cache_key, cache_value, ttl=HttpCache.ttl_for("act"))
        return source_url, html

    async def get_code_list(self, path: str) -> str:
        """Fetch a code-list page (e.g. ``/eli/tipuskodok``, ``/eli/kibocsatokodok``)."""
        return await self._get_cached(f"{self.base_url}{path}", category="dict")
