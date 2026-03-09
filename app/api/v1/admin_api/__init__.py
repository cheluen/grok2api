"""Legacy admin_api compatibility shims."""

from app.api.v1.admin import router

__all__ = ["router"]
