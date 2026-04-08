"""Shared HTTP client with rate limiting and retry logic.

All external API calls must go through a client created by make_client().
Rate limiting is enforced via a thread-safe token bucket — this is not optional.

Usage:
    from broombroom.http import make_client, TokenBucket

    bucket = TokenBucket(rate=3)          # 3 requests/second
    client = make_client(timeout=30, max_retries=3)

    with client as c:
        bucket.acquire()
        response = c.get("https://api.openf1.org/v1/sessions")
"""

import threading
import time

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from broombroom.errors import APIError, RateLimitError
from broombroom.logging import get_logger

log = get_logger(__name__)


class TokenBucket:
    """Thread-safe token bucket rate limiter.

    Args:
        rate: Maximum number of tokens (requests) to allow per second.
    """

    def __init__(self, rate: float) -> None:
        if rate <= 0:
            raise ValueError(f"rate must be positive, got {rate}")
        self._rate = rate
        self._tokens = rate
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> None:
        """Block until the requested number of tokens are available."""
        with self._lock:
            self._refill()
            if self._tokens < tokens:
                wait = (tokens - self._tokens) / self._rate
                time.sleep(wait)
                self._refill()
            self._tokens -= tokens

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
        self._last_refill = now


def _is_retryable(exc: BaseException) -> bool:
    """Return True if the exception warrants a retry."""
    if isinstance(exc, RateLimitError):
        return True
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.NetworkError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return False


def make_client(
    timeout: int = 30,
    max_retries: int = 3,
    headers: dict[str, str] | None = None,
) -> httpx.Client:
    """Create a configured httpx.Client.

    The client is meant to be used as a context manager or reused across calls
    for connection pooling. It does NOT include rate limiting — callers must
    call TokenBucket.acquire() before each request.
    """
    return httpx.Client(
        timeout=httpx.Timeout(timeout),
        headers=headers or {},
        follow_redirects=True,
    )


class RateLimitedSession:
    """Combines an httpx.Client with a TokenBucket for a single API source.

    Provides .get() with built-in rate limiting and tenacity retry.

    Args:
        base_url: API base URL (no trailing slash).
        rate_per_second: Maximum requests per second.
        timeout: Per-request timeout in seconds.
        max_retries: Maximum number of retries on transient errors.
    """

    def __init__(
        self,
        base_url: str,
        rate_per_second: float = 1.0,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._bucket = TokenBucket(rate=rate_per_second)
        self._client = make_client(timeout=timeout)
        self._max_retries = max_retries

    def get(self, path: str, params: dict | None = None) -> dict | list:
        """Perform a GET request with rate limiting and automatic retry.

        Returns the parsed JSON body. Some APIs (jolpica) return a JSON
        object, others (openf1) return a JSON array — callers must handle
        both shapes or narrow the return type at the call site.

        Raises APIError on non-2xx responses after all retries are exhausted.
        """
        url = f"{self._base_url}/{path.lstrip('/')}"

        @retry(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=30),
            retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
            reraise=True,
        )
        def _do_request() -> dict | list:
            self._bucket.acquire()
            log.debug("http_get", url=url, params=params)
            response = self._client.get(url, params=params)
            if response.status_code == 429:
                raise RateLimitError(source=self._base_url, status_code=429, message="rate limit exceeded")
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise APIError(
                    source=self._base_url,
                    status_code=exc.response.status_code,
                    message=exc.response.text[:200],
                ) from exc
            return response.json()

        return _do_request()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "RateLimitedSession":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
