from typing import Optional

from app.services.cf_credentials import get_cf_credentials_facade


async def ensure_cf_clearance() -> Optional[str]:
    bundle = await get_cf_credentials_facade().resolve()
    return bundle.cf_clearance or bundle.cookie_string or None


async def refresh_cf_clearance() -> Optional[str]:
    bundle = await get_cf_credentials_facade().refresh(force=True)
    return bundle.cf_clearance or bundle.cookie_string or None


async def handle_403_refresh() -> None:
    await get_cf_credentials_facade().recover_from_403()


__all__ = ["ensure_cf_clearance", "refresh_cf_clearance", "handle_403_refresh"]
