from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import verify_app_key
from app.core.logger import logger
from app.services.cf_credentials import get_cf_credentials_facade

router = APIRouter(
    prefix="/cf-clearance",
    tags=["CF Clearance"],
    dependencies=[Depends(verify_app_key)],
)


class CFStatusResponse(BaseModel):
    enabled: bool
    selected_source: str
    providers: list[str]
    service_url: Optional[str]
    has_cache: bool
    has_cf_cookies: bool
    cached_clearance: Optional[str]
    browser: Optional[str]
    user_agent: Optional[str]
    legacy_configured: bool
    legacy_ready: bool
    cf_refresh_requested: bool
    cf_refresh_configured: bool
    cf_refresh_ready: bool


class CFRefreshRequest(BaseModel):
    force: bool = False


@router.get("/status", response_model=CFStatusResponse)
async def get_cf_status():
    facade = get_cf_credentials_facade()
    bundle = await facade.inspect()

    return CFStatusResponse(
        enabled=bundle.has_dynamic_provider,
        selected_source=bundle.metadata.get("active_provider", bundle.source),
        providers=list(bundle.providers),
        service_url=bundle.masked_service_url(),
        has_cache=bool(bundle.metadata.get("expires_at")),
        has_cf_cookies=bool(bundle.cf_cookies),
        cached_clearance=bundle.masked_clearance(),
        browser=bundle.browser or None,
        user_agent=bundle.user_agent or None,
        legacy_configured=bool(bundle.metadata.get("legacy_configured", False)),
        legacy_ready=bool(bundle.metadata.get("legacy_ready", False)),
        cf_refresh_requested=bool(bundle.metadata.get("cf_refresh_requested", False)),
        cf_refresh_configured=bool(bundle.metadata.get("cf_refresh_configured", False)),
        cf_refresh_ready=bool(bundle.metadata.get("cf_refresh_ready", False)),
    )


@router.post("/refresh")
async def refresh_cf(request: CFRefreshRequest):
    facade = get_cf_credentials_facade()

    if not facade.has_dynamic_provider():
        raise HTTPException(status_code=400, detail="No dynamic CF credential provider configured")

    logger.info(f"Manual CF credential refresh requested, force={request.force}")
    bundle = await facade.refresh(force=request.force)

    cf_refresh_triggered = bool(bundle.metadata.get("cf_refresh_triggered", False))
    cf_refresh_success = bundle.metadata.get("cf_refresh_success")
    legacy_triggered = bool(bundle.metadata.get("legacy_triggered", False))
    legacy_success = bundle.metadata.get("legacy_success")

    success_flags = [flag for flag in [cf_refresh_success, legacy_success] if flag is not None]
    success = all(success_flags) if success_flags else bool(bundle.is_ready)

    return {
        "success": success,
        "selected_source": bundle.metadata.get("active_provider", bundle.source),
        "providers": list(bundle.providers),
        "cf_clearance": bundle.masked_clearance(),
        "has_cf_cookies": bool(bundle.cf_cookies),
        "legacy": {
            "triggered": legacy_triggered,
            "success": legacy_success,
            "ready": bool(bundle.metadata.get("legacy_ready", False)),
        },
        "cf_refresh": {
            "triggered": cf_refresh_triggered,
            "success": cf_refresh_success,
            "ready": bool(bundle.metadata.get("cf_refresh_ready", False)),
        },
        "message": "CF credentials refreshed successfully" if success else "CF credential refresh did not fully succeed, check logs for details",
    }


@router.post("/invalidate")
async def invalidate_cf():
    facade = get_cf_credentials_facade()
    await facade.invalidate_dynamic_state(clear_cf_refresh_state=True)

    return {
        "success": True,
        "message": "Dynamic CF credential state invalidated",
    }
