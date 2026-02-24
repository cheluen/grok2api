"""
CF Clearance 自动获取服务

通过 cf-credential-service 自动获取 CF Clearance。
"""

import httpx
from typing import Optional, Dict, Any

from app.core.logger import logger
from app.core.config import get_config
from app.services.cf_clearance.cache import (
    CFClearanceCache, 
    CFClearanceCacheManager,
    get_cache_manager
)


class CFClearanceService:
    """CF Clearance 自动获取服务"""
    
    def __init__(self):
        self._cache_manager = get_cache_manager()
    
    def _get_service_url(self) -> Optional[str]:
        return get_config("cf_clearance.service_url")
    
    def _get_api_key(self) -> Optional[str]:
        return get_config("cf_clearance.api_key")
    
    def _get_target_url(self) -> str:
        return get_config("cf_clearance.target_url", "https://grok.com")
    
    def _get_timeout(self) -> int:
        return get_config("cf_clearance.timeout", 120)
    
    def _get_proxy(self) -> Optional[str]:
        return get_config("proxy.base_proxy_url")
    
    def _get_browser(self) -> str:
        return get_config("proxy.browser", "chrome136")
    
    def _get_user_agent(self) -> Optional[str]:
        return get_config("proxy.user_agent")
    
    def is_enabled(self) -> bool:
        service_url = self._get_service_url()
        enabled = bool(service_url)
        logger.debug(f"CF Clearance service enabled: {enabled}, url: {service_url}")
        return enabled
    
    async def fetch_from_service(
        self,
        browser: Optional[str] = None,
        proxy: Optional[str] = None,
        user_agent: Optional[str] = None,
        timeout: Optional[int] = None
    ) -> Optional[CFClearanceCache]:
        service_url = self._get_service_url()
        if not service_url:
            logger.warning("CF Clearance service URL not configured")
            return None
        
        api_key = self._get_api_key()
        target_url = self._get_target_url()
        
        browser = browser or self._get_browser()
        proxy = proxy if proxy is not None else self._get_proxy()
        user_agent = user_agent or self._get_user_agent()
        timeout = timeout or self._get_timeout()
        
        context: Dict[str, Any] = {
            "browser": browser,
        }
        
        if proxy:
            context["proxy"] = proxy
        
        if user_agent:
            context["user_agent"] = user_agent
        
        if timeout:
            context["timeout"] = timeout
        
        payload = {
            "target_url": target_url,
            "context": context
        }
        
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key
        
        full_url = f"{service_url.rstrip('/')}/api/v1/credentials"
        
        logger.info(f"Requesting CF Clearance from: {full_url}")
        logger.debug(f"CF Clearance request payload: browser={browser}, proxy={'***' if proxy else None}, timeout={timeout}")
        
        try:
            async with httpx.AsyncClient(timeout=timeout + 10) as client:
                response = await client.post(
                    full_url,
                    json=payload,
                    headers=headers
                )
                
                logger.info(f"CF Clearance service response: {response.status_code}")
                
                if response.status_code != 200:
                    logger.error(
                        f"CF Clearance service returned {response.status_code}: "
                        f"{response.text[:500]}"
                    )
                    return None
                
                data = response.json()
                
                if not data.get("success"):
                    error = data.get("error", "Unknown error")
                    logger.error(f"CF Clearance service failed: {error}")
                    return None
                
                cache = CFClearanceCache(
                    cf_clearance=data.get("cf_clearance", ""),
                    user_agent=data.get("user_agent", ""),
                    browser=data.get("browser", browser),
                    proxy=proxy,
                    expires_at=data.get("expires_at", 0),
                    cookie_string=data.get("cookie_string"),
                    cookies=data.get("cookies")
                )
                
                logger.info(
                    f"CF Clearance obtained successfully: browser={cache.browser}, "
                    f"cf_clearance={cache.cf_clearance[:20]}..., "
                    f"expires_at={cache.expires_at}"
                )
                
                return cache
                
        except httpx.TimeoutException:
            logger.error(f"CF Clearance service request timeout (timeout={timeout}s)")
            return None
        except Exception as e:
            logger.error(f"Failed to fetch CF Clearance: {e}", exc_info=True)
            return None
    
    async def get_clearance(
        self,
        browser: Optional[str] = None,
        proxy: Optional[str] = None,
        force_refresh: bool = False
    ) -> Optional[str]:
        browser = browser or self._get_browser()
        proxy = proxy if proxy is not None else self._get_proxy()
        
        if not force_refresh:
            cached = await self._cache_manager.get_cached(browser, proxy)
            if cached:
                return cached.cf_clearance
        
        if await self._cache_manager.is_refreshing():
            logger.debug("CF Clearance refresh already in progress, waiting...")
            import asyncio
            for _ in range(30):
                await asyncio.sleep(1)
                cached = await self._cache_manager.get_cached(browser, proxy)
                if cached:
                    return cached.cf_clearance
                if not await self._cache_manager.is_refreshing():
                    break
            return None
        
        await self._cache_manager.set_refreshing(True)
        try:
            cache = await self.fetch_from_service(browser, proxy)
            if cache:
                await self._cache_manager.set_cache(cache)
                return cache.cf_clearance
            return None
        finally:
            await self._cache_manager.set_refreshing(False)
    
    async def get_cache(
        self,
        browser: Optional[str] = None,
        proxy: Optional[str] = None,
        force_refresh: bool = False
    ) -> Optional[CFClearanceCache]:
        browser = browser or self._get_browser()
        proxy = proxy if proxy is not None else self._get_proxy()
        
        if not force_refresh:
            cached = await self._cache_manager.get_cached(browser, proxy)
            if cached:
                return cached
        
        if await self._cache_manager.is_refreshing():
            logger.debug("CF Clearance refresh already in progress, waiting...")
            import asyncio
            for _ in range(30):
                await asyncio.sleep(1)
                cached = await self._cache_manager.get_cached(browser, proxy)
                if cached:
                    return cached
                if not await self._cache_manager.is_refreshing():
                    break
            return None
        
        await self._cache_manager.set_refreshing(True)
        try:
            cache = await self.fetch_from_service(browser, proxy)
            if cache:
                await self._cache_manager.set_cache(cache)
                return cache
            return None
        finally:
            await self._cache_manager.set_refreshing(False)
    
    async def invalidate_cache(self) -> None:
        await self._cache_manager.invalidate()


_service: Optional[CFClearanceService] = None


def get_cf_clearance_service() -> CFClearanceService:
    global _service
    if _service is None:
        _service = CFClearanceService()
    return _service


__all__ = ["CFClearanceService", "get_cf_clearance_service"]
