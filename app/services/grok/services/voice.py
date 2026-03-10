"""
Grok Voice Mode Service
"""

from typing import Any, Dict

from app.services.cf_credentials import resolve_impersonate_browser
from app.services.reverse.ws_livekit import LivekitTokenReverse
from app.services.reverse.utils.session import ResettableSession


class VoiceService:
    """Voice Mode Service (LiveKit)"""

    async def get_token(
        self,
        token: str,
        voice: str = "ara",
        personality: str = "assistant",
        speed: float = 1.0,
    ) -> Dict[str, Any]:
        browser = resolve_impersonate_browser()
        async with ResettableSession(impersonate=browser) as session:
            response = await LivekitTokenReverse.request(
                session,
                token=token,
                voice=voice,
                personality=personality,
                speed=speed,
            )
            return response.json()
