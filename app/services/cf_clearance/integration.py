"""
CF Clearance 集成模块

提供与现有代码集成的便捷功能。
"""

from typing import Optional, Tuple
from app.core.logger import logger
from app.core.config import get_config
from app.services.cf_clearance.service import get_cf_clearance_service


async def ensure_cf_clearance() -> Optional[str]:
    """
    确保有有效的 CF Clearance
    
    如果配置了自动获取服务，会自动获取；
    否则返回配置文件中的静态值。
    
    Returns:
        Optional[str]: CF Clearance 值
    """
    service = get_cf_clearance_service()
    
    if service.is_enabled():
        cf_clearance = await service.get_clearance()
        if cf_clearance:
            return cf_clearance
    
    return get_config("proxy.cf_clearance") or None


async def refresh_cf_clearance() -> Optional[str]:
    """
    强制刷新 CF Clearance
    
    Returns:
        Optional[str]: 新的 CF Clearance 值
    """
    service = get_cf_clearance_service()
    
    if service.is_enabled():
        logger.info("Force refreshing CF Clearance...")
        cf_clearance = await service.get_clearance(force_refresh=True)
        if cf_clearance:
            return cf_clearance
    
    return get_config("proxy.cf_clearance") or None


async def handle_403_refresh() -> None:
    """
    处理 403 错误时自动刷新 CF Clearance
    """
    service = get_cf_clearance_service()
    
    if service.is_enabled():
        logger.warning("403 error detected, invalidating CF Clearance cache")
        await service.invalidate_cache()


__all__ = ["ensure_cf_clearance", "refresh_cf_clearance", "handle_403_refresh"]
