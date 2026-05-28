#!/usr/bin/env python3
"""
food_db_cache.py — Phase 7: TTL-based in-memory cache for food lookups.

Provides a lightweight cache layer in front of food_db_lookup.py without
introducing Redis or any other external dependency.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from food_db_lookup import FoodDBLookup

DEFAULT_DB_PATH = Path(os.environ.get("HEALTHFIT_DB", "~/.healthfit/healthfit.db")).expanduser()
HOT_TTL_SECONDS = 60 * 60
COLD_TTL_SECONDS = 24 * 60 * 60
DEFAULT_MAX_ENTRIES = 512


@dataclass
class CacheEntry:
    key: str
    value: Any
    expires_at: float
    ttl_seconds: int
    created_at: float
    hits: int = 0

    @property
    def expired(self) -> bool:
        return self.expires_at <= self.created_at


class TTLMemoryCache:
    def __init__(
        self,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        time_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self.max_entries = max_entries
        self._time_fn = time_fn or time.time
        self._entries: dict[str, CacheEntry] = {}
        self._hits = 0
        self._misses = 0

    def _now(self) -> float:
        return self._time_fn()

    def _evict_if_needed(self) -> None:
        if len(self._entries) < self.max_entries:
            return
        oldest_key = min(
            self._entries,
            key=lambda key: (self._entries[key].expires_at, self._entries[key].created_at),
        )
        self._entries.pop(oldest_key, None)

    def get(self, key: str) -> Any:
        entry = self._entries.get(key)
        now = self._now()
        if entry is None:
            self._misses += 1
            return None
        if entry.expires_at <= now:
            self._entries.pop(key, None)
            self._misses += 1
            return None
        entry.hits += 1
        self._hits += 1
        return entry.value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        now = self._now()
        self._evict_if_needed()
        self._entries[key] = CacheEntry(
            key=key,
            value=value,
            expires_at=now + ttl_seconds,
            ttl_seconds=ttl_seconds,
            created_at=now,
        )

    def invalidate(self, key: str) -> bool:
        return self._entries.pop(key, None) is not None

    def clear(self) -> int:
        count = len(self._entries)
        self._entries.clear()
        return count

    def purge_expired(self) -> int:
        now = self._now()
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)
        return len(expired)

    def stats(self) -> dict[str, Any]:
        ttl_buckets = {"hot": 0, "cold": 0}
        for entry in self._entries.values():
            if entry.ttl_seconds <= HOT_TTL_SECONDS:
                ttl_buckets["hot"] += 1
            else:
                ttl_buckets["cold"] += 1
        return {
            "size": len(self._entries),
            "hits": self._hits,
            "misses": self._misses,
            "max_entries": self.max_entries,
            "ttl_buckets": ttl_buckets,
        }


class FoodDBCache:
    """
    Cache wrapper around FoodDBLookup.

    Phase 7 boundary:
    - Search results for hot/common foods use 1h TTL.
    - Exact id lookups and cold/empty lookups use 24h TTL.
    """

    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        *,
        lookup_engine: Optional[Any] = None,
        cache: Optional[TTLMemoryCache] = None,
    ) -> None:
        self.lookup = lookup_engine or FoodDBLookup(db_path=db_path)
        self.cache = cache or TTLMemoryCache()

    @staticmethod
    def _normalize_sources(sources: Optional[list[str]]) -> list[str]:
        # Preserve priority order — do NOT sort here
        return list(sources or ["TW_FDA", "USDA"])

    @staticmethod
    def _make_key(prefix: str, payload: dict[str, Any]) -> str:
        return prefix + ":" + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _search_ttl(self, results: list[Any]) -> int:
        if results:
            return HOT_TTL_SECONDS
        return COLD_TTL_SECONDS

    def search(
        self,
        query: str,
        *,
        top: int = 5,
        sources: Optional[list[str]] = None,
        category: Optional[str] = None,
        min_score: float = 0.30,
    ) -> list[Any]:
        payload = {
            "query": query.strip(),
            "top": top,
            "sources": self._normalize_sources(sources),
            "category": category,
            "min_score": round(min_score, 4),
        }
        key = self._make_key("search", payload)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        results = self.lookup.search(
            query,
            top=top,
            sources=sources,
            category=category,
            min_score=min_score,
        )
        self.cache.set(key, results, self._search_ttl(results))
        return results

    def lookup_by_id(self, source: str, food_id: str) -> Any:
        payload = {"source": source, "food_id": food_id}
        key = self._make_key("lookup", payload)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        result = self.lookup.lookup(source, food_id)
        self.cache.set(key, result, COLD_TTL_SECONDS)
        return result

    def search_many(self, queries: list[str], *, top: int = 3) -> dict[str, list[Any]]:
        return {query: self.search(query, top=top) for query in queries}

    def invalidate_search(
        self,
        query: str,
        *,
        top: int = 5,
        sources: Optional[list[str]] = None,
        category: Optional[str] = None,
        min_score: float = 0.30,
    ) -> bool:
        key = self._make_key(
            "search",
            {
                "query": query.strip(),
                "top": top,
                "sources": self._normalize_sources(sources),
                "category": category,
                "min_score": round(min_score, 4),
            },
        )
        return self.cache.invalidate(key)

    def purge_expired(self) -> int:
        return self.cache.purge_expired()

    def stats(self) -> dict[str, Any]:
        return self.cache.stats()


def main() -> None:
    parser = argparse.ArgumentParser(description="HealthFit food lookup cache (Phase 7).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="Search food with cache")
    p_search.add_argument("query")
    p_search.add_argument("--top", type=int, default=5)

    p_lookup = sub.add_parser("lookup", help="Lookup exact food by source and id")
    p_lookup.add_argument("--source", required=True, choices=["TW_FDA", "USDA"])
    p_lookup.add_argument("--id", required=True)

    sub.add_parser("stats", help="Show cache stats")
    sub.add_parser("purge", help="Purge expired cache entries")

    args = parser.parse_args()
    cache = FoodDBCache()

    if args.command == "search":
        results = cache.search(args.query, top=args.top)
        print(json.dumps({
            "query": args.query,
            "count": len(results),
            "items": [
                {
                    "food_name": r.item.food_name,
                    "source": r.item.source,
                    "food_id": r.item.food_id,
                    "match_score": r.match_score,
                }
                for r in results
            ],
        }, ensure_ascii=False, indent=2))
    elif args.command == "lookup":
        item = cache.lookup_by_id(args.source, args.id)
        if item is None:
            print("null")
        else:
            print(json.dumps({
                "source": item.source,
                "food_id": item.food_id,
                "food_name": item.food_name,
                "calories_100g": item.calories_100g,
            }, ensure_ascii=False, indent=2))
    elif args.command == "stats":
        print(json.dumps(cache.stats(), ensure_ascii=False, indent=2))
    elif args.command == "purge":
        print(json.dumps({"purged": cache.purge_expired()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
