"""
CF Clearance 管理 API
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.core.logger import logger
from app.services.cf_clearance import (
    get_cf_clearance_service,
    ensure_cf_clearance,
    refresh_cf_clearance,
    handle_403_refresh
)

router = APIRouter(prefix="/cf-clearance", tags=["CF Clearance"])


class CFStatusResponse(BaseModel):
    enabled: bool
    service_url: Optional[str]
    has_cache: bool
    cached_clearance: Optional[str]


class CFRefreshRequest(BaseModel):
    force: bool = False


@router.get("/status", response_model=CFStatusResponse)
async def get_cf_status():
    service = get_cf_clearance_service()
    
    service_url = service._get_service_url()
    has_cache = False
    cached_clearance = None
    
    if service.is_enabled():
        cache = await service.get_cache()
        if cache:
            has_cache = True
            cached_clearance = cache.cf_clearance[:30] + "..." if cache.cf_clearance else None
    
    return CFStatusResponse(
        enabled=service.is_enabled(),
        service_url=service_url[:50] + "..." if service_url and len(service_url) > 50 else service_url,
        has_cache=has_cache,
        cached_clearance=cached_clearance
    )


@router.post("/refresh")
async def refresh_cf(request: CFRefreshRequest):
    service = get_cf_clearance_service()
    
    if not service.is_enabled():
        raise HTTPException(status_code=400, detail="CF Clearance service not configured")
    
    logger.info(f"Manual CF Clearance refresh requested, force={request.force}")
    
    if request.force:
        await service.invalidate_cache()
    
    cf_clearance = await service.get_clearance(force_refresh=request.force)
    
    if cf_clearance:
        return {
            "success": True,
            "cf_clearance": cf_clearance[:30] + "...",
            "message": "CF Clearance refreshed successfully"
        }
    else:
        return {
            "success": False,
            "cf_clearance": None,
            "message": "Failed to refresh CF Clearance, check logs for details"
        }


@router.post("/invalidate")
async def invalidate_cf():
    service = get_cf_clearance_service()
    await service.invalidate_cache()
    
    return {
        "success": True,
        "message": "CF Clearance cache invalidated"
    }
