import os
import unittest

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core.config import config, get_config
from app.core.auth import get_admin_api_key, verify_api_key, verify_app_key


class TestEnvConfigOverrides(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._saved_env = {
            k: os.environ.get(k)
            for k in (
                "GROK2API_APP_KEY",
                "GROK2API_API_KEY",
                "GROK2API_CF_CLEARANCE",
            )
        }
        for key in self._saved_env:
            os.environ.pop(key, None)

        # 基线配置（模拟来自 config.toml 的值）
        config._config = {
            "app": {"app_key": "from_file_app", "api_key": ""},
            "security": {"cf_clearance": "from_file_cf"},
        }

    def tearDown(self) -> None:
        for key, val in self._saved_env.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val

    def test_env_overrides_app_key(self) -> None:
        os.environ["GROK2API_APP_KEY"] = "env_app_key"
        self.assertEqual(get_config("app.app_key"), "env_app_key")

    def test_env_empty_string_can_disable_api_key(self) -> None:
        config._config["app"]["api_key"] = "from_file_api_key"
        os.environ["GROK2API_API_KEY"] = ""
        self.assertEqual(get_admin_api_key(), "")

    def test_env_overrides_cf_clearance_and_normalizes(self) -> None:
        os.environ["GROK2API_CF_CLEARANCE"] = "foo=1; cf_clearance=abc123; bar=2"
        self.assertEqual(get_config("security.cf_clearance"), "abc123")

    async def test_verify_app_key_uses_env(self) -> None:
        os.environ["GROK2API_APP_KEY"] = "secret"
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="secret")
        result = await verify_app_key(creds)
        self.assertEqual(result, "secret")

    async def test_verify_app_key_rejects_wrong(self) -> None:
        os.environ["GROK2API_APP_KEY"] = "secret"
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong")
        with self.assertRaises(HTTPException):
            await verify_app_key(creds)

    async def test_verify_api_key_enforced_by_env(self) -> None:
        os.environ["GROK2API_API_KEY"] = "api_secret"

        ok = HTTPAuthorizationCredentials(scheme="Bearer", credentials="api_secret")
        self.assertEqual(await verify_api_key(ok), "api_secret")

        bad = HTTPAuthorizationCredentials(scheme="Bearer", credentials="nope")
        with self.assertRaises(HTTPException):
            await verify_api_key(bad)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
