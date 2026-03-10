"""Unified Cloudflare credential facade.

将本地 legacy `cf_clearance` 服务、上游 `cf_refresh` 配置流、以及静态配置
收敛为统一的运行时读取入口，避免请求头构建和管理接口直接耦合具体实现。
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.core.config import config, get_config
from app.core.logger import logger

_CF_CLEARANCE_RE = re.compile(r"(^|;\s*)cf_clearance=[^;]*")
_REQUEST_CF_BUNDLE: ContextVar["CFCredentialsBundle | None"] = ContextVar("request_cf_bundle", default=None)


def _run_coroutine_sync(coro, *, timeout: float = 5.0):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=timeout)
    return asyncio.run(coro)


def _normalize_cookie_string(cookie_string: Optional[str]) -> str:
    return (cookie_string or "").strip().strip(";").strip()


def _merge_cookie_string(cf_cookies: Optional[str], cf_clearance: Optional[str]) -> str:
    merged = _normalize_cookie_string(cf_cookies)
    clearance = (cf_clearance or "").strip()

    if not clearance:
        return merged

    if not merged:
        return f"cf_clearance={clearance}"

    if _CF_CLEARANCE_RE.search(merged):
        return _CF_CLEARANCE_RE.sub(r"\1cf_clearance=" + clearance, merged, count=1)

    return f"{merged}; cf_clearance={clearance}"


def _cookies_dict_to_string(cookies: Optional[dict[str, Any]]) -> str:
    if not isinstance(cookies, dict):
        return ""
    parts: list[str] = []
    for name, value in cookies.items():
        if not name:
            continue
        parts.append(f"{name}={value or ''}")
    return "; ".join(parts)


def _mask_secret(value: Optional[str], *, keep: int = 30) -> Optional[str]:
    if not value:
        return None
    if len(value) <= keep:
        return value
    return value[:keep] + "..."


@dataclass
class CFCredentialsBundle:
    source: str = "config"
    cf_clearance: str = ""
    cf_cookies: str = ""
    user_agent: str = ""
    browser: str = ""
    service_url: Optional[str] = None
    cf_refresh_enabled: bool = False
    legacy_service_enabled: bool = False
    providers: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def cookie_string(self) -> str:
        return _merge_cookie_string(self.cf_cookies, self.cf_clearance)

    @property
    def has_dynamic_provider(self) -> bool:
        return self.cf_refresh_enabled or self.legacy_service_enabled

    @property
    def is_ready(self) -> bool:
        return bool((self.cf_cookies or self.cf_clearance) and self.user_agent and self.browser)

    def masked_clearance(self) -> Optional[str]:
        return _mask_secret(self.cf_clearance)

    def masked_service_url(self) -> Optional[str]:
        return _mask_secret(self.service_url, keep=50)


class CFCredentialsFacade:
    """统一管理 Cloudflare 凭证来源。"""

    def __init__(self):
        self._cf_refresh_recovery_task: Optional[asyncio.Task] = None

    def _is_cf_refresh_requested(self) -> bool:
        return bool(get_config("proxy.enabled", False))

    def _has_cf_refresh_solver(self) -> bool:
        return bool(get_config("proxy.flaresolverr_url") or "")

    def _build_config_bundle(self) -> CFCredentialsBundle:
        cf_refresh_enabled = self._is_cf_refresh_requested()
        source = "cf_refresh" if cf_refresh_enabled else "config"
        providers = (source,)
        bundle = CFCredentialsBundle(
            source=source,
            cf_clearance=get_config("proxy.cf_clearance") or "",
            cf_cookies=get_config("proxy.cf_cookies") or "",
            user_agent=get_config("proxy.user_agent") or "",
            browser=get_config("proxy.browser") or "",
            cf_refresh_enabled=cf_refresh_enabled,
            providers=providers,
            metadata={
                "cf_refresh_requested": cf_refresh_enabled,
                "cf_refresh_configured": self._has_cf_refresh_solver(),
            },
        )
        bundle.metadata["cf_refresh_ready"] = bundle.is_ready
        return bundle

    async def _get_legacy_bundle(
        self,
        *,
        fetch: bool,
        force_refresh: bool = False,
    ) -> CFCredentialsBundle:
        from app.services.cf_clearance import get_cf_clearance_service

        service = get_cf_clearance_service()
        service_url = service._get_service_url()
        bundle = CFCredentialsBundle(
            source="cf_clearance_service",
            service_url=service_url,
            legacy_service_enabled=service.is_enabled(),
            cf_refresh_enabled=self._is_cf_refresh_requested(),
            providers=(("cf_clearance_service",) if service.is_enabled() else ()),
            metadata={"legacy_configured": service.is_enabled()},
        )

        if not service.is_enabled():
            bundle.metadata["legacy_ready"] = False
            return bundle

        try:
            if force_refresh:
                cache = await service.get_cache(force_refresh=True)
            elif fetch:
                cache = await service.get_cache()
            else:
                cache = await service.peek_cache()
        except Exception as exc:
            logger.debug(f"Failed to resolve legacy CF credentials: {exc}")
            bundle.metadata["legacy_ready"] = False
            return bundle

        if not cache:
            bundle.metadata["legacy_ready"] = False
            return bundle

        cookie_string = cache.cookie_string or _cookies_dict_to_string(cache.cookies)
        bundle.cf_clearance = cache.cf_clearance or ""
        bundle.cf_cookies = cookie_string
        bundle.user_agent = cache.user_agent or ""
        bundle.browser = cache.browser or ""
        bundle.metadata.update(
            {
                "expires_at": cache.expires_at,
                "proxy": cache.proxy,
                "legacy_ready": bundle.is_ready,
            }
        )
        return bundle

    @staticmethod
    def _copy_bundle(bundle: CFCredentialsBundle, **kwargs: Any) -> CFCredentialsBundle:
        payload = {
            "source": bundle.source,
            "cf_clearance": bundle.cf_clearance,
            "cf_cookies": bundle.cf_cookies,
            "user_agent": bundle.user_agent,
            "browser": bundle.browser,
            "service_url": bundle.service_url,
            "cf_refresh_enabled": bundle.cf_refresh_enabled,
            "legacy_service_enabled": bundle.legacy_service_enabled,
            "providers": bundle.providers,
            "metadata": dict(bundle.metadata),
        }
        payload.update(kwargs)
        return CFCredentialsBundle(**payload)

    @staticmethod
    def _can_use_legacy_as_active(
        base: CFCredentialsBundle,
        legacy: CFCredentialsBundle,
    ) -> bool:
        if not legacy.legacy_service_enabled:
            return False
        if not legacy.user_agent or not legacy.browser:
            return False
        if legacy.cf_cookies:
            return True
        if legacy.cf_clearance and not base.cf_cookies:
            return True
        return False

    @classmethod
    def _select_active_bundle(
        cls,
        base: CFCredentialsBundle,
        legacy: CFCredentialsBundle,
    ) -> CFCredentialsBundle:
        providers = tuple(dict.fromkeys([*base.providers, *legacy.providers]))
        status_meta = {
            "cf_refresh_requested": base.metadata.get("cf_refresh_requested", False),
            "cf_refresh_configured": base.metadata.get("cf_refresh_configured", False),
            "cf_refresh_ready": base.metadata.get("cf_refresh_ready", False),
            "legacy_configured": legacy.metadata.get("legacy_configured", legacy.legacy_service_enabled),
            "legacy_ready": legacy.metadata.get("legacy_ready", False),
        }

        if cls._can_use_legacy_as_active(base, legacy):
            metadata = {**status_meta, **legacy.metadata, "active_provider": legacy.source}
            return cls._copy_bundle(
                legacy,
                cf_refresh_enabled=base.cf_refresh_enabled or legacy.cf_refresh_enabled,
                legacy_service_enabled=legacy.legacy_service_enabled,
                providers=providers,
                metadata=metadata,
            )

        metadata = {**status_meta, **base.metadata, "active_provider": base.source}
        return cls._copy_bundle(
            base,
            service_url=legacy.service_url or base.service_url,
            legacy_service_enabled=legacy.legacy_service_enabled,
            providers=providers or base.providers,
            metadata=metadata,
        )

    async def inspect(self) -> CFCredentialsBundle:
        config_bundle = self._build_config_bundle()
        legacy_bundle = await self._get_legacy_bundle(fetch=False)
        return self._select_active_bundle(config_bundle, legacy_bundle)

    async def resolve(self, *, force_refresh: bool = False) -> CFCredentialsBundle:
        config_bundle = self._build_config_bundle()
        legacy_bundle = await self._get_legacy_bundle(fetch=True, force_refresh=force_refresh)
        return self._select_active_bundle(config_bundle, legacy_bundle)

    def inspect_sync(self) -> CFCredentialsBundle:
        return _run_coroutine_sync(self.inspect())

    def resolve_sync(self, *, force_refresh: bool = False, timeout: float = 15.0) -> CFCredentialsBundle:
        return _run_coroutine_sync(self.resolve(force_refresh=force_refresh), timeout=timeout)

    async def prewarm(self) -> CFCredentialsBundle:
        """仅预热本地 legacy 服务；cf_refresh 仍由后台调度自行刷新。"""
        if not self.is_legacy_service_enabled():
            return await self.inspect()
        logger.info("Pre-warming legacy CF credential provider...")
        return await self.resolve(force_refresh=True)

    async def refresh(self, *, force: bool = False) -> CFCredentialsBundle:
        """主动刷新所有已启用的动态 provider，并返回合并后的结果。"""
        legacy_configured = self.is_legacy_service_enabled()
        cf_refresh_triggered = False
        cf_refresh_success: Optional[bool] = None

        if force:
            await self.invalidate_dynamic_state(clear_cf_refresh_state=self._is_cf_refresh_requested())

        if self._is_cf_refresh_requested():
            cf_refresh_triggered = True
            try:
                from app.services.cf_refresh.scheduler import refresh_once

                cf_refresh_success = await refresh_once()
            except Exception as exc:
                logger.warning(f"Failed to refresh cf_refresh provider: {exc}")
                cf_refresh_success = False

        config_bundle = self._build_config_bundle()
        legacy_bundle = await self._get_legacy_bundle(fetch=legacy_configured, force_refresh=force and legacy_configured)
        bundle = self._select_active_bundle(config_bundle, legacy_bundle)
        bundle.metadata.update(
            {
                "cf_refresh_triggered": cf_refresh_triggered,
                "cf_refresh_success": cf_refresh_success,
                "legacy_triggered": legacy_configured,
                "legacy_success": legacy_bundle.is_ready if legacy_configured else None,
                "force": force,
            }
        )
        return bundle

    async def invalidate_dynamic_state(self, *, clear_cf_refresh_state: bool = False) -> None:
        if self.is_legacy_service_enabled():
            from app.services.cf_clearance import get_cf_clearance_service

            service = get_cf_clearance_service()
            await service.invalidate_cache()

        if clear_cf_refresh_state and self._is_cf_refresh_requested():
            await config.update({"proxy": {"cf_cookies": "", "cf_clearance": ""}})

    async def _run_cf_refresh_recovery(self) -> None:
        try:
            from app.services.cf_refresh.scheduler import refresh_once

            refreshed = await refresh_once()
            logger.warning(f"Triggered background cf_refresh recovery after 403: success={refreshed}")
        except Exception as exc:
            logger.debug(f"Failed to trigger background cf_refresh recovery on 403: {exc}")
        finally:
            self._cf_refresh_recovery_task = None

    def _schedule_cf_refresh_recovery(self) -> None:
        task = self._cf_refresh_recovery_task
        if task is not None and not task.done():
            return
        self._cf_refresh_recovery_task = asyncio.create_task(self._run_cf_refresh_recovery())

    async def recover_from_403(self) -> None:
        """403 时触发动态 provider 自愈。"""
        if self.is_legacy_service_enabled():
            try:
                await self.invalidate_dynamic_state()
                logger.warning("Invalidated legacy CF credential cache after 403")
            except Exception as exc:
                logger.debug(f"Failed to invalidate legacy CF cache on 403: {exc}")

        if self._is_cf_refresh_requested():
            self._schedule_cf_refresh_recovery()

    def is_legacy_service_enabled(self) -> bool:
        from app.services.cf_clearance import get_cf_clearance_service

        return get_cf_clearance_service().is_enabled()

    def has_dynamic_provider(self) -> bool:
        return self._is_cf_refresh_requested() or self.is_legacy_service_enabled()


_facade: Optional[CFCredentialsFacade] = None


def get_cf_credentials_facade() -> CFCredentialsFacade:
    global _facade
    if _facade is None:
        _facade = CFCredentialsFacade()
    return _facade


def resolve_request_bundle_sync(*, force_refresh: bool = False) -> CFCredentialsBundle:
    cached = _REQUEST_CF_BUNDLE.get()
    if cached is not None and not force_refresh:
        return cached

    facade = get_cf_credentials_facade()
    try:
        bundle = facade.resolve_sync(force_refresh=force_refresh, timeout=15.0)
    except Exception as exc:
        logger.debug(f"Failed to resolve active CF bundle: {exc}")
        try:
            bundle = facade.inspect_sync()
        except Exception as inner_exc:
            logger.debug(f"Failed to inspect active CF bundle: {inner_exc}")
            bundle = CFCredentialsBundle()

    _REQUEST_CF_BUNDLE.set(bundle)
    return bundle


async def resolve_request_bundle_async(*, force_refresh: bool = False) -> CFCredentialsBundle:
    cached = _REQUEST_CF_BUNDLE.get()
    if cached is not None and not force_refresh:
        return cached

    facade = get_cf_credentials_facade()
    try:
        bundle = await facade.resolve(force_refresh=force_refresh)
    except Exception as exc:
        logger.debug(f"Failed to async-resolve active CF bundle: {exc}")
        try:
            bundle = await facade.inspect()
        except Exception as inner_exc:
            logger.debug(f"Failed to async-inspect active CF bundle: {inner_exc}")
            bundle = CFCredentialsBundle()

    _REQUEST_CF_BUNDLE.set(bundle)
    return bundle


def resolve_impersonate_browser(default: Optional[str] = None) -> str:
    bundle = resolve_request_bundle_sync()
    fallback = default if default is not None else (get_config("proxy.browser") or "chrome136")
    return bundle.browser or fallback


__all__ = [
    "CFCredentialsBundle",
    "CFCredentialsFacade",
    "get_cf_credentials_facade",
    "resolve_impersonate_browser",
    "resolve_request_bundle_async",
    "resolve_request_bundle_sync",
]
