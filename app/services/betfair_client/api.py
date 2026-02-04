"""Betfair Exchange API client.

Provides async access to Betfair's betting exchange API with:
- Automatic authentication
- Rate limiting
- Retry with exponential backoff
- Error classification
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

import httpx
import redis.asyncio as redis
import structlog

from app.config import get_settings
from app.services.betfair_client.auth import BetfairAuth, BetfairAuthError
from app.services.betfair_client.rate_limiter import BetfairRateLimiter

logger = structlog.get_logger(__name__)

# Betfair API URLs
BETTING_API_URL = "https://api.betfair.com/exchange/betting/rest/v1.0"


class BetfairErrorType(Enum):
    """Classification of Betfair API errors."""

    INVALID_SESSION = "INVALID_SESSION"
    TOO_MUCH_DATA = "TOO_MUCH_DATA"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    INVALID_INPUT = "INVALID_INPUT"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class BetfairAPIError(Exception):
    """Betfair API error with classification."""

    def __init__(self, message: str, error_type: BetfairErrorType, retryable: bool = False):
        super().__init__(message)
        self.error_type = error_type
        self.retryable = retryable


@dataclass
class EventType:
    """Sport/event type from Betfair."""

    id: str
    name: str
    market_count: int = 0


@dataclass
class Competition:
    """League/competition from Betfair."""

    id: str
    name: str
    region: str | None = None
    market_count: int = 0


@dataclass
class Event:
    """Match/event from Betfair."""

    id: str
    name: str
    competition_id: str | None = None
    venue: str | None = None
    timezone: str | None = None
    open_date: datetime | None = None
    market_count: int = 0


@dataclass
class Runner:
    """Selection within a market."""

    selection_id: int
    runner_name: str
    handicap: float = 0.0
    sort_priority: int = 0
    status: str = "ACTIVE"


@dataclass
class MarketCatalogue:
    """Market metadata from Betfair."""

    market_id: str
    market_name: str
    market_type: str
    event_id: str
    event_name: str
    competition_id: str | None = None
    total_matched: Decimal = Decimal("0")
    runners: list[Runner] = field(default_factory=list)


@dataclass
class PriceSize:
    """Price and size at a level."""

    price: Decimal
    size: Decimal


@dataclass
class RunnerBook:
    """Runner prices and volumes."""

    selection_id: int
    status: str
    last_price_traded: Decimal | None = None
    total_matched: Decimal = Decimal("0")
    back_prices: list[PriceSize] = field(default_factory=list)
    lay_prices: list[PriceSize] = field(default_factory=list)


@dataclass
class MarketBook:
    """Live market prices and state."""

    market_id: str
    is_market_data_delayed: bool = False
    status: str = "OPEN"
    in_play: bool = False
    total_matched: Decimal = Decimal("0")
    total_available: Decimal = Decimal("0")
    runners: list[RunnerBook] = field(default_factory=list)


class BetfairClient:
    """
    Betfair Exchange API client.

    Supports:
    - Session token authentication (interactive + certificate)
    - Rate limiting (5 req/sec default)
    - Automatic retry with exponential backoff
    - Error classification and handling
    """

    def __init__(
        self,
        redis_client: redis.Redis | None = None,
        rate_limiter: BetfairRateLimiter | None = None,
        auth: BetfairAuth | None = None,
    ):
        """
        Initialize Betfair client.

        Args:
            redis_client: Redis client for caching and rate limiting
            rate_limiter: Optional custom rate limiter
            auth: Optional custom auth handler
        """
        self.settings = get_settings()
        self.redis = redis_client
        self.auth = auth or BetfairAuth(redis_client)
        self.rate_limiter = rate_limiter or (
            BetfairRateLimiter(redis_client) if redis_client else None
        )
        self._http_client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "BetfairClient":
        """Async context manager entry."""
        self._http_client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    async def _request(
        self,
        endpoint: str,
        params: dict[str, Any],
        max_retries: int = 3,
    ) -> Any:
        """
        Make an API request with rate limiting and retry.

        Args:
            endpoint: API endpoint name
            params: Request parameters
            max_retries: Maximum retry attempts

        Returns:
            API response data

        Raises:
            BetfairAPIError: If request fails after retries
        """
        url = f"{BETTING_API_URL}/{endpoint}/"

        for attempt in range(max_retries + 1):
            try:
                # Rate limit
                if self.rate_limiter:
                    await self.rate_limiter.wait_if_needed(endpoint)

                # Get session token
                token = await self.auth.get_session_token()

                # Make request
                client = await self._get_client()
                response = await client.post(
                    url,
                    json=params,
                    headers={
                        "X-Application": self.settings.betfair_app_key,
                        "X-Authentication": token,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )

                # Check for HTTP errors
                response.raise_for_status()

                # Parse response
                data = response.json()

                # Check for API-level errors
                if isinstance(data, dict) and "error" in data:
                    error_code = data.get("error", {}).get("code", "UNKNOWN")
                    error_msg = data.get("error", {}).get("message", "Unknown error")
                    error_type, retryable = self._classify_error(error_code)

                    if error_type == BetfairErrorType.INVALID_SESSION:
                        # Re-authenticate and retry
                        await self.auth.logout()
                        await self.auth.login()
                        continue

                    if retryable and attempt < max_retries:
                        wait_time = 2**attempt
                        logger.warning(
                            "api_error_retrying",
                            endpoint=endpoint,
                            error=error_code,
                            attempt=attempt,
                            wait_time=wait_time,
                        )
                        await asyncio.sleep(wait_time)
                        continue

                    raise BetfairAPIError(error_msg, error_type, retryable)

                return data

            except httpx.TimeoutException:
                if attempt < max_retries:
                    wait_time = 2**attempt
                    logger.warning(
                        "timeout_retrying",
                        endpoint=endpoint,
                        attempt=attempt,
                        wait_time=wait_time,
                    )
                    await asyncio.sleep(wait_time)
                    continue
                raise BetfairAPIError(
                    "Request timeout",
                    BetfairErrorType.TIMEOUT,
                    retryable=True,
                )

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:  # Rate limited
                    if attempt < max_retries:
                        wait_time = 2**attempt
                        logger.warning(
                            "rate_limited_retrying",
                            endpoint=endpoint,
                            attempt=attempt,
                        )
                        await asyncio.sleep(wait_time)
                        continue
                    raise BetfairAPIError(
                        "Rate limited",
                        BetfairErrorType.RATE_LIMITED,
                        retryable=True,
                    )
                elif e.response.status_code == 400:
                    # Bad Request - likely invalid market IDs or parameters
                    logger.warning(
                        "bad_request",
                        endpoint=endpoint,
                        status_code=400,
                        response_text=e.response.text[:500] if e.response.text else "",
                    )
                    raise BetfairAPIError(
                        f"Client error '400 Bad Request': {e.response.text[:200] if e.response.text else 'Invalid request'}",
                        BetfairErrorType.INVALID_INPUT,
                        retryable=False,
                    )
                elif e.response.status_code >= 500:
                    if attempt < max_retries:
                        wait_time = 2**attempt
                        await asyncio.sleep(wait_time)
                        continue
                    raise BetfairAPIError(
                        f"Server error: {e.response.status_code}",
                        BetfairErrorType.SERVICE_UNAVAILABLE,
                        retryable=True,
                    )
                raise BetfairAPIError(
                    str(e),
                    BetfairErrorType.UNKNOWN,
                    retryable=False,
                )

            except BetfairAuthError as e:
                raise BetfairAPIError(
                    str(e),
                    BetfairErrorType.INVALID_SESSION,
                    retryable=True,
                )

    def _classify_error(self, error_code: str) -> tuple[BetfairErrorType, bool]:
        """Classify error code and determine if retryable."""
        error_mapping = {
            "INVALID_SESSION_INFORMATION": (BetfairErrorType.INVALID_SESSION, True),
            "NO_SESSION": (BetfairErrorType.INVALID_SESSION, True),
            "TOO_MUCH_DATA": (BetfairErrorType.TOO_MUCH_DATA, False),
            "INVALID_INPUT_DATA": (BetfairErrorType.INVALID_INPUT, False),
            "INVALID_APP_KEY": (BetfairErrorType.INVALID_INPUT, False),
            "SERVICE_BUSY": (BetfairErrorType.SERVICE_UNAVAILABLE, True),
            "TIMEOUT_ERROR": (BetfairErrorType.TIMEOUT, True),
        }
        return error_mapping.get(error_code, (BetfairErrorType.UNKNOWN, False))

    async def list_event_types(self) -> list[EventType]:
        """
        Fetch all sports/event types.

        Returns:
            List of available sports
        """
        data = await self._request("listEventTypes", {"filter": {}})
        return [
            EventType(
                id=item["eventType"]["id"],
                name=item["eventType"]["name"],
                market_count=item.get("marketCount", 0),
            )
            for item in data
        ]

    async def list_competitions(
        self,
        sport_ids: list[str] | None = None,
        market_countries: list[str] | None = None,
    ) -> list[Competition]:
        """
        Fetch competitions for given sports.

        Args:
            sport_ids: Filter by sport IDs
            market_countries: Filter by country codes

        Returns:
            List of competitions
        """
        filter_params: dict[str, Any] = {}
        if sport_ids:
            filter_params["eventTypeIds"] = sport_ids
        if market_countries:
            filter_params["marketCountries"] = market_countries

        data = await self._request("listCompetitions", {"filter": filter_params})
        return [
            Competition(
                id=item["competition"]["id"],
                name=item["competition"]["name"],
                region=item.get("competitionRegion"),
                market_count=item.get("marketCount", 0),
            )
            for item in data
        ]

    async def list_events(
        self,
        competition_ids: list[str] | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        sport_ids: list[str] | None = None,
    ) -> list[Event]:
        """
        Fetch events within time window.

        Args:
            competition_ids: Filter by competition IDs
            from_time: Start of time window
            to_time: End of time window
            sport_ids: Filter by sport IDs

        Returns:
            List of events
        """
        filter_params: dict[str, Any] = {}
        if competition_ids:
            filter_params["competitionIds"] = competition_ids
        if sport_ids:
            filter_params["eventTypeIds"] = sport_ids
        if from_time or to_time:
            filter_params["marketStartTime"] = {}
            if from_time:
                filter_params["marketStartTime"]["from"] = from_time.isoformat()
            if to_time:
                filter_params["marketStartTime"]["to"] = to_time.isoformat()

        data = await self._request("listEvents", {"filter": filter_params})

        events = []
        for item in data:
            event_data = item["event"]
            open_date = None
            if event_data.get("openDate"):
                try:
                    open_date = datetime.fromisoformat(
                        event_data["openDate"].replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    pass

            events.append(
                Event(
                    id=event_data["id"],
                    name=event_data["name"],
                    venue=event_data.get("venue"),
                    timezone=event_data.get("timezone"),
                    open_date=open_date,
                    market_count=item.get("marketCount", 0),
                )
            )
        return events

    async def list_market_catalogue(
        self,
        event_ids: list[str] | None = None,
        competition_ids: list[str] | None = None,
        market_types: list[str] | None = None,
        max_results: int = 200,
    ) -> list[MarketCatalogue]:
        """
        Fetch market metadata.

        Args:
            event_ids: Filter by event IDs
            competition_ids: Filter by competition IDs
            market_types: Filter by market types
            max_results: Maximum results to return

        Returns:
            List of market catalogues
        """
        filter_params: dict[str, Any] = {}
        if event_ids:
            filter_params["eventIds"] = event_ids
        if competition_ids:
            filter_params["competitionIds"] = competition_ids
        if market_types:
            filter_params["marketTypeCodes"] = market_types

        data = await self._request(
            "listMarketCatalogue",
            {
                "filter": filter_params,
                "maxResults": str(max_results),
                "marketProjection": [
                    "EVENT",
                    "COMPETITION",
                    "RUNNER_DESCRIPTION",
                    "MARKET_DESCRIPTION",
                ],
            },
        )

        markets = []
        for item in data:
            runners = []
            for runner_data in item.get("runners", []):
                runners.append(
                    Runner(
                        selection_id=runner_data["selectionId"],
                        runner_name=runner_data.get("runnerName", "Unknown"),
                        handicap=runner_data.get("handicap", 0.0),
                        sort_priority=runner_data.get("sortPriority", 0),
                    )
                )

            event = item.get("event", {})
            competition = item.get("competition", {})
            description = item.get("description", {})

            markets.append(
                MarketCatalogue(
                    market_id=item["marketId"],
                    market_name=item.get("marketName", ""),
                    market_type=description.get("marketType", "UNKNOWN"),
                    event_id=event.get("id", ""),
                    event_name=event.get("name", ""),
                    competition_id=competition.get("id"),
                    total_matched=Decimal(str(item.get("totalMatched", 0))),
                    runners=runners,
                )
            )
        return markets

    async def list_market_book(
        self,
        market_ids: list[str],
        price_depth: int = 3,
    ) -> list[MarketBook]:
        """
        Fetch live prices and depth.

        Args:
            market_ids: Market IDs to fetch
            price_depth: Number of price levels per side

        Returns:
            List of market books with prices
        """
        data = await self._request(
            "listMarketBook",
            {
                "marketIds": market_ids,
                "priceProjection": {
                    "priceData": ["EX_BEST_OFFERS", "EX_TRADED"],
                    "exBestOffersOverrides": {
                        "bestPricesDepth": price_depth,
                    },
                },
            },
        )

        books = []
        for item in data:
            runners = []
            for runner_data in item.get("runners", []):
                back_prices = []
                lay_prices = []

                ex = runner_data.get("ex", {})
                for bp in ex.get("availableToBack", []):
                    back_prices.append(
                        PriceSize(
                            price=Decimal(str(bp["price"])),
                            size=Decimal(str(bp["size"])),
                        )
                    )
                for lp in ex.get("availableToLay", []):
                    lay_prices.append(
                        PriceSize(
                            price=Decimal(str(lp["price"])),
                            size=Decimal(str(lp["size"])),
                        )
                    )

                runners.append(
                    RunnerBook(
                        selection_id=runner_data["selectionId"],
                        status=runner_data.get("status", "ACTIVE"),
                        last_price_traded=Decimal(str(runner_data["lastPriceTraded"]))
                        if runner_data.get("lastPriceTraded")
                        else None,
                        total_matched=Decimal(str(runner_data.get("totalMatched", 0))),
                        back_prices=back_prices,
                        lay_prices=lay_prices,
                    )
                )

            books.append(
                MarketBook(
                    market_id=item["marketId"],
                    is_market_data_delayed=item.get("isMarketDataDelayed", False),
                    status=item.get("status", "OPEN"),
                    in_play=item.get("inplay", False),
                    total_matched=Decimal(str(item.get("totalMatched", 0))),
                    total_available=Decimal(str(item.get("totalAvailable", 0))),
                    runners=runners,
                )
            )
        return books

    async def health_check(self) -> bool:
        """
        Check if Betfair API is accessible.

        Returns:
            True if API is healthy
        """
        try:
            await self.list_event_types()
            return True
        except Exception as e:
            logger.error("betfair_health_check_failed", error=str(e))
            return False
