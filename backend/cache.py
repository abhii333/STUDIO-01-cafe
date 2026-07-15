"""Simple in-memory TTL cache for API responses.

Designed for a single-worker deployment (free tier): the cache lives in the
process and is shared across all threads via the GIL. No Redis needed.

Usage:
    from cache import api_cache

    @app.route('/api/menu')
    def api_menu():
        cached = api_cache.get('menu')
        if cached: return cached
        # ... compute response ...
        api_cache.set('menu', response, ttl=60)
        return response

    # Invalidate when admin changes menu:
    api_cache.invalidate('menu')
"""
import time
import threading


class InMemoryCache:
    def __init__(self):
        self._store = {}  # key -> (response_data, expire_at)
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key):
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            data, expire_at = entry
            if time.time() > expire_at:
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            return data

    def set(self, key, data, ttl=60):
        with self._lock:
            self._store[key] = (data, time.time() + ttl)

    def invalidate(self, *keys):
        """Remove one or more keys immediately (call after admin mutations)."""
        with self._lock:
            for key in keys:
                self._store.pop(key, None)

    def clear(self):
        """Flush everything (e.g. on deploy/restart — happens naturally anyway)."""
        with self._lock:
            self._store.clear()

    @property
    def stats(self):
        return {'hits': self._hits, 'misses': self._misses, 'size': len(self._store)}


# Singleton cache instance shared across all blueprints.
api_cache = InMemoryCache()

# TTL configuration (seconds). Admin-editable data uses shorter TTLs so
# changes appear quickly; truly static data uses longer ones.
CACHE_TTL_MENU = 120       # 2 minutes (changes when admin edits menu)
CACHE_TTL_REVIEWS = 300    # 5 minutes (changes when customers review)
CACHE_TTL_SOLDOUT = 30     # 30 seconds (can change frequently during rush)
CACHE_TTL_SPECIAL = 120    # 2 minutes
CACHE_TTL_EVENTS = 300     # 5 minutes
CACHE_TTL_OFFERS = 300     # 5 minutes
CACHE_TTL_PHOTOS = 300     # 5 minutes
