"""Betfair authentication handler.

Supports both certificate-based and interactive login authentication.
Session tokens are cached in Redis with automatic refresh.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any

import httpx
import redis.asyncio as redis
import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)

# Betfair API URLs
CERT_LOGIN_URL = "https://identitysso-cert.betfair.com/api/certlogin"
INTERACTIVE_LOGIN_URL = "https://identitysso.betfair.com/api/login"
LOGOUT_URL = "https://identitysso.betfair.com/api/logout"
KEEPALIVE_URL = "https://identitysso.betfair.com/api/keepAlive"


class BetfairAuthError(Exception):
    """Raised when Betfair authentication fails."""

    pass


class BetfairAuth:
    """
    Handle Betfair authentication.

    Supports:
    - Certificate-based authentication (preferred for automation)
    - Interactive login (fallback)
    - Session token caching in Redis
    - Automatic token refresh
    """

    TOKEN_TTL_SECONDS = 4 * 60 * 60  # 4 hours (Betfair tokens expire after 8h)
    REDIS_TOKEN_KEY = "betfair:session_token"
    REDIS_TOKEN_EXPIRY_KEY = "betfair:token_expiry"

    def __init__(self, redis_client: redis.Redis | None = None):
        """
        Initialize Betfair authentication handler.

        Args:
            redis_client: Optional Redis client for token caching
        """
        self.settings = get_settings()
        self.redis = redis_client
        self._token: str | None = None
        self._token_expiry: datetime | None = None
        self._lock = asyncio.Lock()

    async def login(self) -> str:
        """
        Authenticate with Betfair and return session token.

        Prefers certificate auth if cert path provided.
        Caches token in Redis with TTL.

        Returns:
            Session token string

        Raises:
            BetfairAuthError: If authentication fails
        """
        async with self._lock:
            # Check if we have a valid cached token
            token = await self._get_cached_token()
            if token:
                logger.debug("using_cached_token")
                return token

            # Attempt authentication
            if self.settings.betfair_cert_path:
                token = await self._cert_login()
            else:
                token = await self._interactive_login()

            # Cache the token
            await self._cache_token(token)

            logger.info("betfair_login_success")
            return token

    async def get_session_token(self) -> str:
        """
        Get current session token, refreshing if needed.

        Returns:
            Valid session token

        Raises:
            BetfairAuthError: If unable to obtain token
        """
        # Check in-memory cache first
        if self._token and self._token_expiry and datetime.utcnow() < self._token_expiry:
            return self._token

        # Try to get from Redis or login
        return await self.login()

    async def logout(self) -> None:
        """Invalidate the current session."""
        token = self._token or await self._get_cached_token()
        if not token:
            return

        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    LOGOUT_URL,
                    headers={
                        "X-Application": self.settings.betfair_app_key,
                        "X-Authentication": token,
                    },
                )
        except Exception as e:
            logger.warning("logout_error", error=str(e))

        # Clear cached token
        self._token = None
        self._token_expiry = None
        if self.redis:
            await self.redis.delete(self.REDIS_TOKEN_KEY)
            await self.redis.delete(self.REDIS_TOKEN_EXPIRY_KEY)

        logger.info("betfair_logout_success")

    async def keep_alive(self) -> bool:
        """
        Send keepalive to extend session.

        Returns:
            True if session extended, False otherwise
        """
        token = await self.get_session_token()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    KEEPALIVE_URL,
                    headers={
                        "X-Application": self.settings.betfair_app_key,
                        "X-Authentication": token,
                    },
                )
                data = response.json()
                if data.get("status") == "SUCCESS":
                    # Extend cache TTL
                    await self._cache_token(token)
                    logger.debug("keepalive_success")
                    return True
                else:
                    logger.warning("keepalive_failed", response=data)
                    return False
        except Exception as e:
            logger.error("keepalive_error", error=str(e))
            return False

    async def _cert_login(self) -> str:
        """
        Authenticate using SSL certificate.

        Returns:
            Session token

        Raises:
            BetfairAuthError: If login fails
        """
        if not self.settings.betfair_cert_path:
            raise BetfairAuthError("Certificate path not configured")

        cert_path = self.settings.betfair_cert_path
        key_path = self.settings.betfair_cert_key_path or cert_path.replace(
            ".crt", ".key"
        )

        try:
            async with httpx.AsyncClient(
                cert=(cert_path, key_path),
                verify=True,
            ) as client:
                response = await client.post(
                    CERT_LOGIN_URL,
                    data={
                        "username": self.settings.betfair_username,
                        "password": self.settings.betfair_password,
                    },
                    headers={
                        "X-Application": self.settings.betfair_app_key,
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                return self._parse_login_response(response.json())
        except httpx.HTTPError as e:
            logger.error("cert_login_http_error", error=str(e))
            raise BetfairAuthError(f"Certificate login HTTP error: {e}")
        except Exception as e:
            logger.error("cert_login_error", error=str(e))
            raise BetfairAuthError(f"Certificate login failed: {e}")

    async def _interactive_login(self) -> str:
        """
        Authenticate using username/password.

        Returns:
            Session token

        Raises:
            BetfairAuthError: If login fails
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    INTERACTIVE_LOGIN_URL,
                    data={
                        "username": self.settings.betfair_username,
                        "password": self.settings.betfair_password,
                    },
                    headers={
                        "X-Application": self.settings.betfair_app_key,
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "application/json",
                    },
                )
                return self._parse_login_response(response.json())
        except httpx.HTTPError as e:
            logger.error("interactive_login_http_error", error=str(e))
            raise BetfairAuthError(f"Interactive login HTTP error: {e}")
        except Exception as e:
            logger.error("interactive_login_error", error=str(e))
            raise BetfairAuthError(f"Interactive login failed: {e}")

    def _parse_login_response(self, data: dict[str, Any]) -> str:
        """Parse login response and extract token."""
        status = data.get("loginStatus") or data.get("status")

        if status == "SUCCESS":
            token = data.get("sessionToken") or data.get("token")
            if token:
                return token
            raise BetfairAuthError("No token in successful response")

        error = data.get("error") or data.get("loginStatus") or "Unknown error"
        raise BetfairAuthError(f"Login failed: {error}")

    async def _get_cached_token(self) -> str | None:
        """Get token from cache (Redis or memory)."""
        # Check memory cache
        if self._token and self._token_expiry and datetime.utcnow() < self._token_expiry:
            return self._token

        # Check Redis cache
        if self.redis:
            try:
                token = await self.redis.get(self.REDIS_TOKEN_KEY)
                if token:
                    expiry_str = await self.redis.get(self.REDIS_TOKEN_EXPIRY_KEY)
                    if expiry_str:
                        expiry = datetime.fromisoformat(expiry_str.decode())
                        if datetime.utcnow() < expiry:
                            self._token = token.decode()
                            self._token_expiry = expiry
                            return self._token
            except Exception as e:
                logger.warning("redis_get_token_error", error=str(e))

        return None

    async def _cache_token(self, token: str) -> None:
        """Cache token in Redis and memory."""
        expiry = datetime.utcnow() + timedelta(seconds=self.TOKEN_TTL_SECONDS)

        # Memory cache
        self._token = token
        self._token_expiry = expiry

        # Redis cache
        if self.redis:
            try:
                await self.redis.set(
                    self.REDIS_TOKEN_KEY,
                    token,
                    ex=self.TOKEN_TTL_SECONDS,
                )
                await self.redis.set(
                    self.REDIS_TOKEN_EXPIRY_KEY,
                    expiry.isoformat(),
                    ex=self.TOKEN_TTL_SECONDS,
                )
            except Exception as e:
                logger.warning("redis_cache_token_error", error=str(e))
