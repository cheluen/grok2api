"""
CF Clearance 缓存管理

管理 CF Clearance Cookie 的缓存和有效性验证。
"""

import time
import asyncio
from typing import Optional, Dict, Any
from dataclasses import dataclass

from app.core.logger import logger


@dataclass
class CFClearanceCache:
    cf_clearance: str
    user_agent: str
    browser: str
    proxy: Optional[str]
    expires_at: float
    cookie_string: Optional[str] = None
    cookies: Optional[Dict[str, str]] = None
    
    def is_expired(self, buffer_seconds: int = 300) -> bool:
        if not self.expires_at:
            return True
        return time.time() >= (self.expires_at - buffer_seconds)
    
    def is_valid_for(self, browser: str, proxy: Optional[str]) -> bool:
        if self.is_expired():
            return False
        if self.browser != browser:
            return False
        if self.proxy != proxy:
            return False
        return True


class CFClearanceCacheManager:
    """CF Clearance 缓存管理器"""
    
    def __init__(self):
        self._cache: Optional[CFClearanceCache] = None
        self._lock = asyncio.Lock()
        self._refreshing = False
    
    async def get_cached(
        self, 
        browser: str, 
        proxy: Optional[str]
    ) -> Optional[CFClearanceCache]:
        async with self._lock:
            if self._cache and self._cache.is_valid_for(browser, proxy):
                logger.debug(
                    f"CF Clearance cache hit: browser={browser}, "
                    f"expires_in={int(self._cache.expires_at - time.time())}s"
                )
                return self._cache
            return None
    
    async def set_cache(self, cache: CFClearanceCache) -> None:
        async with self._lock:
            self._cache = cache
            logger.info(
                f"CF Clearance cached: browser={cache.browser}, "
                f"expires_at={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(cache.expires_at))}"
            )
    
    async def invalidate(self) -> None:
        async with self._lock:
            self._cache = None
            logger.info("CF Clearance cache invalidated")
    
    async def is_refreshing(self) -> bool:
        async with self._lock:
            return self._refreshing
    
    async def set_refreshing(self, value: bool) -> None:
        async with self._lock:
            self._refreshing = value


_cache_manager: Optional[CFClearanceCacheManager] = None


def get_cache_manager() -> CFClearanceCacheManager:
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CFClearanceCacheManager()
    return _cache_manager


__all__ = ["CFClearanceCache", "CFClearanceCacheManager", "get_cache_manager"]
