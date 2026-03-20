"""
NSE Index Constituent Fetcher.

Fetches real-time index constituent data from NSE India's public API.
Supports 16 NIFTY sector/broad indices with caching to avoid rate limits.

Usage:
    service = NSEIndexService()
    constituents = await service.get_constituents("NIFTY 50")
    all_data = await service.get_all_constituents()
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from app.services.redis_client import redis_get, redis_set

logger = logging.getLogger(__name__)


# ── Index Name Mapping ──────────────────────────────────────────────────────
# NSE API uses slightly different names in URL params vs response metadata.
# Key: our canonical name → Value: URL query parameter name

INDEX_URL_NAMES: dict[str, str] = {
    "NIFTY 50": "NIFTY 50",
    "NIFTY BANK": "NIFTY BANK",
    "NIFTY IT": "NIFTY IT",
    "NIFTY FIN SERVICE": "NIFTY FINANCIAL SERVICES",  # URL uses full name
    "NIFTY PHARMA": "NIFTY PHARMA",
    "NIFTY AUTO": "NIFTY AUTO",
    "NIFTY METAL": "NIFTY METAL",
    "NIFTY ENERGY": "NIFTY ENERGY",
    "NIFTY FMCG": "NIFTY FMCG",
    "NIFTY REALTY": "NIFTY REALTY",
    "NIFTY INFRA": "NIFTY INFRA",
    "NIFTY PSU BANK": "NIFTY PSU BANK",
    "NIFTY MEDIA": "NIFTY MEDIA",
    "NIFTY MIDCAP 50": "NIFTY MIDCAP 50",
    "NIFTY MIDCAP 100": "NIFTY MIDCAP 100",
    "NIFTY MID SELECT": "NIFTY MID SELECT",
}

AVAILABLE_INDICES = list(INDEX_URL_NAMES.keys())

NSE_BASE_URL = "https://www.nseindia.com"
NSE_API_URL = f"{NSE_BASE_URL}/api/equity-stockIndices"

# Modern browser User-Agent — NSE's Akamai CDN validates this
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)

# Common headers sent with every request
_BASE_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept-Language": "en-GB,en;q=0.6",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    # Client hints — required by NSE's Akamai CDN to pass bot detection
    "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Linux"',
}

# Headers for the initial homepage hit (browser navigation)
_SESSION_HEADERS = {
    **_BASE_HEADERS,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# Headers for API calls (XHR from the page)
_API_HEADERS = {
    **_BASE_HEADERS,
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nseindia.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


# ── Data Classes ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class IndexConstituent:
    """A single stock that is part of an index."""

    symbol: str
    company_name: str
    isin: str
    industry: str
    last_price: float
    change: float  # absolute change
    change_pct: float  # percentage change
    ffmc: float  # free-float market cap (for weightage calculation)
    is_fno: bool  # available in F&O segment
    series: str  # EQ, BE, etc.

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "isin": self.isin,
            "industry": self.industry,
            "last_price": self.last_price,
            "change": self.change,
            "change_pct": self.change_pct,
            "ffmc": self.ffmc,
            "is_fno": self.is_fno,
            "series": self.series,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> IndexConstituent:
        return cls(
            symbol=d["symbol"],
            company_name=d["company_name"],
            isin=d["isin"],
            industry=d["industry"],
            last_price=d["last_price"],
            change=d["change"],
            change_pct=d["change_pct"],
            ffmc=d["ffmc"],
            is_fno=d["is_fno"],
            series=d["series"],
        )


@dataclass
class IndexData:
    """Complete data for an index including all constituents."""

    index_name: str
    last_price: float
    change: float
    change_pct: float
    constituents: list[IndexConstituent]
    fetched_at: float = field(default_factory=time.time)  # epoch timestamp

    @property
    def symbols(self) -> list[str]:
        """Return just the trading symbols."""
        return [c.symbol for c in self.constituents]

    @property
    def constituent_count(self) -> int:
        return len(self.constituents)

    def get_weightages(self) -> dict[str, float]:
        """Calculate approximate weightage from free-float market cap."""
        total_ffmc = sum(c.ffmc for c in self.constituents)
        if total_ffmc <= 0:
            return {c.symbol: 0.0 for c in self.constituents}
        return {
            c.symbol: round((c.ffmc / total_ffmc) * 100, 4)
            for c in self.constituents
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize for Redis storage."""
        return {
            "index_name": self.index_name,
            "last_price": self.last_price,
            "change": self.change,
            "change_pct": self.change_pct,
            "constituents": [c.to_dict() for c in self.constituents],
            "fetched_at": self.fetched_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> IndexData:
        """Deserialize from Redis storage."""
        return cls(
            index_name=d["index_name"],
            last_price=d["last_price"],
            change=d["change"],
            change_pct=d["change_pct"],
            constituents=[IndexConstituent.from_dict(c) for c in d["constituents"]],
            fetched_at=d.get("fetched_at", time.time()),
        )


# ── Service ─────────────────────────────────────────────────────────────────


class NSEIndexError(Exception):
    """Raised when NSE API requests fail."""

    def __init__(self, message: str, index_name: str = "", status_code: int = 0):
        super().__init__(message)
        self.index_name = index_name
        self.status_code = status_code


class NSEIndexService:
    """
    Fetches NIFTY index constituent stocks from NSE India's public API.

    NSE requires browser-like headers and session cookies. This service:
    1. Establishes a session by hitting the NSE homepage (gets cookies).
    2. Uses the session to query the equity-stockIndices API.
    3. Caches results in-memory (short TTL for live prices) AND Redis
       (24h TTL for constituent lists that change quarterly).

    Lookup order: in-memory → Redis → NSE API.
    Session cookies expire every ~5-10 minutes; the service auto-refreshes.
    """

    # Redis key prefix and TTL (24 hours)
    REDIS_PREFIX = "nse:index:"
    REDIS_TTL = 86400  # 24 hours

    def __init__(
        self,
        cache_ttl_seconds: int = 300,  # 5 minutes default (in-memory)
        request_timeout: float = 30.0,
        rate_limit_delay: float = 1.0,  # seconds between API calls
    ):
        self._cache_ttl = cache_ttl_seconds
        self._timeout = request_timeout
        self._rate_limit_delay = rate_limit_delay
        self._cache: dict[str, IndexData] = {}
        self._client: httpx.AsyncClient | None = None
        self._session_established: bool = False
        self._session_time: float = 0.0
        self._last_request_time: float = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client with session cookies."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=_API_HEADERS,
                follow_redirects=True,
                timeout=self._timeout,
            )
            self._session_established = False

        # Re-establish session if expired (every 4 minutes to be safe)
        if not self._session_established or (time.time() - self._session_time > 240):
            await self._establish_session()

        return self._client

    async def _establish_session(self) -> None:
        """Hit NSE homepage to get session cookies.

        Uses browser-navigation headers (not API headers) because NSE's
        Akamai CDN checks Sec-Fetch-* values to distinguish real browsers
        from bots.
        """
        if self._client is None:
            raise NSEIndexError("HTTP client not initialized")

        try:
            resp = await self._client.get(NSE_BASE_URL, headers=_SESSION_HEADERS)
            resp.raise_for_status()
            self._session_established = True
            self._session_time = time.time()
            logger.debug("NSE session established (cookies: %s)", list(self._client.cookies.keys()))
        except httpx.HTTPError as e:
            logger.warning("Failed to establish NSE session: %s", e)
            raise NSEIndexError(f"Failed to establish NSE session: {e}")

    async def _rate_limit(self) -> None:
        """Enforce rate limiting between API calls."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._rate_limit_delay:
            await asyncio.sleep(self._rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    def _parse_constituents(self, data: dict[str, Any]) -> IndexData:
        """Parse NSE API response into IndexData."""
        items = data.get("data", [])
        metadata = data.get("metadata", {})

        if not items:
            raise NSEIndexError("Empty response data from NSE API")

        # First item with priority=1 is the index aggregate row
        index_row = None
        constituents: list[IndexConstituent] = []

        for item in items:
            if item.get("priority") == 1:
                index_row = item
                continue

            # priority=0 items are constituent stocks
            meta = item.get("meta", {})
            constituents.append(IndexConstituent(
                symbol=item.get("symbol", ""),
                company_name=meta.get("companyName", item.get("symbol", "")),
                isin=meta.get("isin", ""),
                industry=meta.get("industry", ""),
                last_price=float(item.get("lastPrice", 0) or 0),
                change=float(item.get("change", 0) or 0),
                change_pct=float(item.get("pChange", 0) or 0),
                ffmc=float(item.get("ffmc", 0) or 0),
                is_fno=bool(meta.get("isFNOSec")),
                series=meta.get("series", "EQ"),
            ))

        # Extract index-level data
        index_name = metadata.get("indexName", "")
        index_price = 0.0
        index_change = 0.0
        index_change_pct = 0.0

        if index_row:
            index_price = float(index_row.get("lastPrice", 0) or 0)
            index_change = float(index_row.get("change", 0) or 0)
            index_change_pct = float(index_row.get("pChange", 0) or 0)
            if not index_name:
                index_name = index_row.get("symbol", "UNKNOWN")

        return IndexData(
            index_name=index_name,
            last_price=index_price,
            change=index_change,
            change_pct=index_change_pct,
            constituents=constituents,
        )

    async def get_constituents(
        self,
        index_name: str,
        force_refresh: bool = False,
    ) -> IndexData:
        """
        Fetch constituent stocks for a given NIFTY index.

        Args:
            index_name: Canonical index name (e.g. "NIFTY 50", "NIFTY BANK")
            force_refresh: Bypass cache and fetch fresh data

        Returns:
            IndexData with all constituent stocks

        Raises:
            NSEIndexError: If the index name is unknown or the API call fails
        """
        if index_name not in INDEX_URL_NAMES:
            raise NSEIndexError(
                f"Unknown index: '{index_name}'. Available: {AVAILABLE_INDICES}",
                index_name=index_name,
            )

        # Check in-memory cache
        if not force_refresh and index_name in self._cache:
            cached = self._cache[index_name]
            age = time.time() - cached.fetched_at
            if age < self._cache_ttl:
                logger.debug("Cache hit (memory) for %s (age=%.0fs)", index_name, age)
                return cached

        # Check Redis cache (longer TTL — 24h for constituent lists)
        if not force_refresh:
            redis_key = f"{self.REDIS_PREFIX}{index_name}"
            redis_data = await redis_get(redis_key)
            if redis_data is not None:
                try:
                    result = IndexData.from_dict(redis_data)
                    # Store in memory cache too (for faster subsequent lookups)
                    self._cache[index_name] = result
                    logger.debug("Cache hit (Redis) for %s", index_name)
                    return result
                except (KeyError, TypeError, ValueError) as e:
                    logger.warning("Redis data corrupt for %s, fetching fresh: %s", index_name, e)

        # Fetch from NSE
        url_name = INDEX_URL_NAMES[index_name]
        client = await self._get_client()
        await self._rate_limit()

        try:
            resp = await client.get(
                NSE_API_URL,
                params={"index": url_name},
            )

            if resp.status_code == 401 or resp.status_code == 403:
                # Session expired, re-establish and retry
                logger.info("NSE session expired, re-establishing...")
                await self._establish_session()
                await self._rate_limit()
                resp = await client.get(
                    NSE_API_URL,
                    params={"index": url_name},
                )

            resp.raise_for_status()
            data = resp.json()

        except httpx.HTTPStatusError as e:
            raise NSEIndexError(
                f"NSE API returned {e.response.status_code} for {index_name}",
                index_name=index_name,
                status_code=e.response.status_code,
            )
        except httpx.HTTPError as e:
            raise NSEIndexError(
                f"NSE API request failed for {index_name}: {e}",
                index_name=index_name,
            )

        result = self._parse_constituents(data)
        self._cache[index_name] = result

        # Persist to Redis (24h TTL — constituents change quarterly)
        redis_key = f"{self.REDIS_PREFIX}{index_name}"
        await redis_set(redis_key, result.to_dict(), ttl=self.REDIS_TTL)

        logger.info(
            "Fetched %d constituents for %s (last=%.2f, chg=%.2f%%)",
            result.constituent_count, index_name, result.last_price, result.change_pct,
        )
        return result

    async def get_all_constituents(
        self,
        indices: list[str] | None = None,
        force_refresh: bool = False,
    ) -> dict[str, IndexData]:
        """
        Fetch constituents for multiple indices (defaults to all 16).

        Fetches sequentially to respect NSE rate limits.

        Returns:
            Dict mapping index name → IndexData
        """
        target_indices = indices or AVAILABLE_INDICES
        results: dict[str, IndexData] = {}
        errors: list[str] = []

        for idx_name in target_indices:
            try:
                results[idx_name] = await self.get_constituents(
                    idx_name, force_refresh=force_refresh
                )
            except NSEIndexError as e:
                logger.warning("Failed to fetch %s: %s", idx_name, e)
                errors.append(f"{idx_name}: {e}")

        if errors:
            logger.warning("Some indices failed: %s", errors)

        return results

    async def get_constituent_symbols(
        self,
        index_name: str,
        force_refresh: bool = False,
    ) -> list[str]:
        """
        Get just the trading symbols for an index.

        Convenience method for when you only need the symbol list.
        """
        data = await self.get_constituents(index_name, force_refresh=force_refresh)
        return data.symbols

    async def get_all_constituent_symbols(
        self,
        indices: list[str] | None = None,
        force_refresh: bool = False,
    ) -> dict[str, list[str]]:
        """
        Get symbol lists for multiple indices.

        Returns:
            Dict mapping index name → list of symbols
        """
        all_data = await self.get_all_constituents(indices, force_refresh=force_refresh)
        return {name: data.symbols for name, data in all_data.items()}

    def clear_cache(self) -> None:
        """Clear all cached data."""
        self._cache.clear()
        logger.debug("NSE index cache cleared")

    def get_cache_status(self) -> dict[str, Any]:
        """Return cache status for monitoring."""
        now = time.time()
        return {
            "cached_indices": list(self._cache.keys()),
            "cache_ttl_seconds": self._cache_ttl,
            "entries": {
                name: {
                    "constituents": data.constituent_count,
                    "age_seconds": round(now - data.fetched_at),
                    "expired": (now - data.fetched_at) >= self._cache_ttl,
                }
                for name, data in self._cache.items()
            },
        }

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
            self._session_established = False
        logger.debug("NSE index service closed")

    async def __aenter__(self) -> NSEIndexService:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
