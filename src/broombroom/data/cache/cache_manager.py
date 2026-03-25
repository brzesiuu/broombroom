"""File-based TTL cache for jolpica and openf1 API responses.

Each cached entry is stored as two files:
  {cache_dir}/{sha256_key}.json       — the response body
  {cache_dir}/{sha256_key}.meta.json  — metadata (timestamp, ttl, source)

This is intentionally simple — no SQLite, no Redis.
Finished race data gets an infinite TTL (ttl_seconds=0).
"""

import hashlib
import json
import time
from pathlib import Path

from broombroom.errors import CacheError
from broombroom.logging import get_logger

log = get_logger(__name__)

_INFINITE_TTL = 0  # sentinel: never expire


class CacheManager:
    """Simple file-based cache with per-entry TTL.

    Args:
        cache_dir: Directory where cache files are stored.
    """

    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ─────────────────────────────────────────────────────────────

    def get(self, key: str) -> dict | list | None:
        """Return cached value if it exists and has not expired, else None."""
        data_path, meta_path = self._paths(key)
        if not data_path.exists() or not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text())
            if self._is_expired(meta):
                log.debug("cache_miss_expired", key=key[:12])
                return None
            value = json.loads(data_path.read_text())
            log.debug("cache_hit", key=key[:12])
            return value
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("cache_read_error", key=key[:12], error=str(exc))
            return None

    def put(
        self,
        key: str,
        data: dict | list,
        ttl_seconds: int,
        source: str = "",
    ) -> None:
        """Write data to the cache with the given TTL.

        Args:
            key: Cache key (will be hashed internally).
            data: JSON-serialisable payload to cache.
            ttl_seconds: Seconds until expiry. 0 = never expire (finished sessions).
            source: Human-readable label for the API source (for debugging).
        """
        data_path, meta_path = self._paths(key)
        meta = {
            "stored_at": time.time(),
            "ttl_seconds": ttl_seconds,
            "source": source,
        }
        try:
            data_path.write_text(json.dumps(data, default=str))
            meta_path.write_text(json.dumps(meta))
            log.debug("cache_put", key=key[:12], ttl=ttl_seconds, source=source)
        except OSError as exc:
            raise CacheError(f"Failed to write cache entry for key {key[:12]!r}: {exc}") from exc

    def invalidate(self, key: str) -> None:
        """Remove a cache entry if it exists."""
        for path in self._paths(key):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                log.warning("cache_invalidate_error", key=key[:12], error=str(exc))

    def clear_all(self) -> int:
        """Remove all cache entries. Returns the number of entries deleted."""
        count = 0
        for f in self._dir.glob("*.json"):
            try:
                f.unlink()
                count += 1
            except OSError:
                pass
        # Each entry = 2 files; return logical entry count
        return count // 2

    def clear_source(self, source: str) -> int:
        """Remove all entries whose metadata matches a given source label."""
        removed = 0
        for meta_path in self._dir.glob("*.meta.json"):
            try:
                meta = json.loads(meta_path.read_text())
                if meta.get("source") == source:
                    data_path = meta_path.with_suffix("").with_suffix(".json")
                    data_path.unlink(missing_ok=True)
                    meta_path.unlink(missing_ok=True)
                    removed += 1
            except (json.JSONDecodeError, OSError):
                pass
        return removed

    # ── Internal helpers ───────────────────────────────────────────────────────

    @staticmethod
    def make_key(*parts: str) -> str:
        """Derive a stable cache key from arbitrary string parts."""
        combined = "|".join(parts)
        return hashlib.sha256(combined.encode()).hexdigest()

    def _paths(self, key: str) -> tuple[Path, Path]:
        hashed = hashlib.sha256(key.encode()).hexdigest()
        return self._dir / f"{hashed}.json", self._dir / f"{hashed}.meta.json"

    @staticmethod
    def _is_expired(meta: dict) -> bool:
        ttl = meta.get("ttl_seconds", _INFINITE_TTL)
        if ttl == _INFINITE_TTL:
            return False
        stored_at = meta.get("stored_at", 0.0)
        return (time.time() - stored_at) > ttl


# ── TTL constants (use these when calling put()) ───────────────────────────────

TTL_INFINITE = _INFINITE_TTL          # finished race sessions, historical results
TTL_STANDINGS = 30 * 60               # 30 minutes — current-season standings
TTL_SCHEDULE = 60 * 60               # 1 hour — season schedule
TTL_LIVE = 5 * 60                    # 5 minutes — live/in-progress session data
