# src/services/cache_service.py
"""
Redis caching service for therapist data.
Supports both local Redis and AWS ElastiCache.
"""
import hashlib
import json
import logging
import os
import pickle
from datetime import timedelta
from typing import Any, Dict, List, Optional, Union

import redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class CacheService:
    """Redis caching service with fallback to memory cache."""

    def __init__(self):
        """Initialize Redis connection."""
        self.redis_client = None
        self.memory_cache = {}  # Fallback memory cache
        self.connected = False

        # Redis configuration
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", 6379))
        redis_password = os.getenv("REDIS_PASSWORD", None)
        redis_ssl = os.getenv("REDIS_SSL", "false").lower() == "true"

        # ElastiCache configuration for AWS
        elasticache_endpoint = os.getenv("ELASTICACHE_ENDPOINT")

        try:
            if elasticache_endpoint:
                # AWS ElastiCache connection
                self.redis_client = redis.Redis(
                    host=elasticache_endpoint,
                    port=6379,
                    password=redis_password,
                    ssl=redis_ssl,
                    decode_responses=False,  # We'll handle encoding/decoding
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                logger.info(f"Connected to ElastiCache at {elasticache_endpoint}")
            else:
                # Local Redis connection
                self.redis_client = redis.Redis(
                    host=redis_host,
                    port=redis_port,
                    password=redis_password,
                    decode_responses=False,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                logger.info(f"Connected to Redis at {redis_host}:{redis_port}")

            # Test connection
            self.redis_client.ping()
            self.connected = True

        except (RedisError, Exception) as e:
            logger.warning(
                f"Redis connection failed: {str(e)}. Using memory cache fallback."
            )
            self.connected = False

    def _generate_key(self, prefix: str, params: Dict[str, Any]) -> str:
        """Generate a cache key from prefix and parameters."""
        # Sort params for consistent key generation
        sorted_params = json.dumps(params, sort_keys=True)
        param_hash = hashlib.md5(sorted_params.encode()).hexdigest()[:8]
        return f"solhealth:{prefix}:{param_hash}"

    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        if self.connected and self.redis_client:
            try:
                value = self.redis_client.get(key)
                if value:
                    return pickle.loads(value)
            except RedisError as e:
                logger.error(f"Redis get error: {str(e)}")

        # Fallback to memory cache
        return self.memory_cache.get(key)

    def set(self, key: str, value: Any, ttl_seconds: int = 300) -> bool:
        """
        Set value in cache with TTL.

        Args:
            key: Cache key
            value: Value to cache
            ttl_seconds: Time to live in seconds (default 5 minutes)

        Returns:
            True if successful
        """
        serialized_value = pickle.dumps(value)

        if self.connected and self.redis_client:
            try:
                self.redis_client.setex(
                    key, timedelta(seconds=ttl_seconds), serialized_value
                )
                return True
            except RedisError as e:
                logger.error(f"Redis set error: {str(e)}")

        # Fallback to memory cache
        self.memory_cache[key] = value
        # Simple TTL for memory cache (not production-ready)
        # In production, use a proper TTL implementation
        return True

    def delete(self, key: str) -> bool:
        """Delete a key from cache."""
        deleted = False

        if self.connected and self.redis_client:
            try:
                deleted = bool(self.redis_client.delete(key))
            except RedisError as e:
                logger.error(f"Redis delete error: {str(e)}")

        # Also delete from memory cache
        if key in self.memory_cache:
            del self.memory_cache[key]
            deleted = True

        return deleted

    def clear_pattern(self, pattern: str) -> int:
        """
        Clear all keys matching a pattern.

        Args:
            pattern: Redis key pattern (e.g., "solhealth:therapist:*")

        Returns:
            Number of keys deleted
        """
        count = 0

        if self.connected and self.redis_client:
            try:
                # Use SCAN to find keys (better than KEYS for production)
                cursor = 0
                while True:
                    cursor, keys = self.redis_client.scan(
                        cursor, match=pattern, count=100
                    )
                    if keys:
                        count += self.redis_client.delete(*keys)
                    if cursor == 0:
                        break
            except RedisError as e:
                logger.error(f"Redis clear pattern error: {str(e)}")

        # Clear from memory cache
        keys_to_delete = [
            k
            for k in self.memory_cache.keys()
            if k.startswith(pattern.replace("*", ""))
        ]
        for key in keys_to_delete:
            del self.memory_cache[key]
            count += 1

        return count

    # Specific methods for therapist data

    def get_all_therapists(self) -> Optional[List[Dict[str, Any]]]:
        """Get all therapists from cache."""
        return self.get("solhealth:therapists:all")

    def set_all_therapists(
        self, therapists: List[Dict[str, Any]], ttl_seconds: int = 1800  # 30 minutes
    ) -> bool:
        """Cache all therapists."""
        return self.set("solhealth:therapists:all", therapists, ttl_seconds)

    def get_therapist_match(
        self, payment_type: str, state: str, specialties: List[str]
    ) -> Optional[List[Dict[str, Any]]]:
        """Get cached therapist match results."""
        key = self._generate_key(
            "match",
            {
                "payment_type": payment_type,
                "state": state,
                "specialties": sorted(specialties),
            },
        )
        return self.get(key)

    def set_therapist_match(
        self,
        payment_type: str,
        state: str,
        specialties: List[str],
        results: List[Dict[str, Any]],
        ttl_seconds: int = 600,  # 10 minutes
    ) -> bool:
        """Cache therapist match results."""
        key = self._generate_key(
            "match",
            {
                "payment_type": payment_type,
                "state": state,
                "specialties": sorted(specialties),
            },
        )
        return self.set(key, results, ttl_seconds)

    def get_therapist_search(
        self, query: str, payment_type: str, state: str
    ) -> Optional[List[Dict[str, Any]]]:
        """Get cached search results."""
        key = self._generate_key(
            "search",
            {"query": query.lower(), "payment_type": payment_type, "state": state},
        )
        return self.get(key)

    def set_therapist_search(
        self,
        query: str,
        payment_type: str,
        state: str,
        results: List[Dict[str, Any]],
        ttl_seconds: int = 300,  # 5 minutes
    ) -> bool:
        """Cache search results."""
        key = self._generate_key(
            "search",
            {"query": query.lower(), "payment_type": payment_type, "state": state},
        )
        return self.set(key, results, ttl_seconds)

    def invalidate_therapist_cache(self) -> int:
        """Invalidate all therapist-related cache."""
        count = 0
        count += self.clear_pattern("solhealth:therapists:*")
        count += self.clear_pattern("solhealth:match:*")
        count += self.clear_pattern("solhealth:search:*")
        logger.info(f"Invalidated {count} therapist cache entries")
        return count

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        stats = {
            "connected": self.connected,
            "backend": "redis" if self.connected else "memory",
            "memory_cache_size": len(self.memory_cache),
        }

        if self.connected and self.redis_client:
            try:
                info = self.redis_client.info()
                stats.update(
                    {
                        "redis_version": info.get("redis_version"),
                        "used_memory_human": info.get("used_memory_human"),
                        "connected_clients": info.get("connected_clients"),
                        "total_connections_received": info.get(
                            "total_connections_received"
                        ),
                        "keyspace_hits": info.get("keyspace_hits", 0),
                        "keyspace_misses": info.get("keyspace_misses", 0),
                    }
                )

                # Calculate hit rate
                hits = stats["keyspace_hits"]
                misses = stats["keyspace_misses"]
                if hits + misses > 0:
                    stats["hit_rate"] = round(hits / (hits + misses) * 100, 2)

            except RedisError as e:
                logger.error(f"Error getting Redis stats: {str(e)}")

        return stats


# Create singleton instance
cache_service = CacheService()
