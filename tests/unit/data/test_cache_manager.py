"""Unit tests for the file-based cache manager."""

import time
from pathlib import Path

import pytest

from broombroom.data.cache.cache_manager import CacheManager, TTL_INFINITE


@pytest.fixture()
def cache(tmp_path: Path) -> CacheManager:
    return CacheManager(tmp_path / "cache")


class TestCacheManager:
    def test_miss_on_empty(self, cache: CacheManager) -> None:
        assert cache.get("nonexistent") is None

    def test_put_and_get(self, cache: CacheManager) -> None:
        payload = {"season": 2024, "round": 5}
        cache.put("mykey", payload, ttl_seconds=3600)
        result = cache.get("mykey")
        assert result == payload

    def test_list_payload(self, cache: CacheManager) -> None:
        payload = [{"driver": "VER"}, {"driver": "NOR"}]
        cache.put("list_key", payload, ttl_seconds=60)
        assert cache.get("list_key") == payload

    def test_infinite_ttl_never_expires(self, cache: CacheManager) -> None:
        cache.put("inf_key", {"x": 1}, ttl_seconds=TTL_INFINITE)
        assert cache.get("inf_key") is not None

    def test_expired_entry_returns_none(self, cache: CacheManager) -> None:
        cache.put("short", {"x": 1}, ttl_seconds=1)
        time.sleep(1.1)
        assert cache.get("short") is None

    def test_invalidate(self, cache: CacheManager) -> None:
        cache.put("del_me", {"x": 1}, ttl_seconds=3600)
        assert cache.get("del_me") is not None
        cache.invalidate("del_me")
        assert cache.get("del_me") is None

    def test_invalidate_missing_key_is_safe(self, cache: CacheManager) -> None:
        cache.invalidate("does_not_exist")  # should not raise

    def test_make_key_is_deterministic(self) -> None:
        k1 = CacheManager.make_key("jolpica", "race_results", "2024", "5")
        k2 = CacheManager.make_key("jolpica", "race_results", "2024", "5")
        assert k1 == k2

    def test_make_key_different_parts_differ(self) -> None:
        k1 = CacheManager.make_key("jolpica", "2024", "5")
        k2 = CacheManager.make_key("jolpica", "2024", "6")
        assert k1 != k2

    def test_clear_source(self, cache: CacheManager) -> None:
        cache.put("a", {"x": 1}, ttl_seconds=3600, source="jolpica")
        cache.put("b", {"y": 2}, ttl_seconds=3600, source="openf1")
        removed = cache.clear_source("jolpica")
        assert removed == 1
        assert cache.get("a") is None
        assert cache.get("b") is not None

    def test_clear_all(self, cache: CacheManager) -> None:
        cache.put("x", {"a": 1}, ttl_seconds=3600)
        cache.put("y", {"b": 2}, ttl_seconds=3600)
        count = cache.clear_all()
        assert count == 2
        assert cache.get("x") is None
        assert cache.get("y") is None
