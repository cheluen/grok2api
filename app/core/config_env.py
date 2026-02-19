"""
配置环境变量覆盖层。

约定：
- 环境变量前缀：GROK2API_CONFIG__
- 映射规则：section.key -> GROK2API_CONFIG__SECTION__KEY
- 作用：在运行时覆盖持久化配置，且覆盖项可用于前端锁定。
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
import os
import re
from typing import Any, Dict, Mapping, Sequence

DEFAULT_ENV_PREFIX = "GROK2API_CONFIG__"
_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
_FALSE_VALUES = {"0", "false", "no", "n", "off"}
_ENV_SEGMENT_PATTERN = re.compile(r"[^A-Z0-9]+")


@dataclass
class EnvOverrideResult:
    overrides: Dict[str, Any] = field(default_factory=dict)
    locked_paths: Dict[str, str] = field(default_factory=dict)
    errors: Dict[str, str] = field(default_factory=dict)


class EnvConfigOverlay:
    """根据默认配置结构，从环境变量构建运行时覆盖层。"""

    def __init__(
        self,
        prefix: str = DEFAULT_ENV_PREFIX,
        environ: Mapping[str, str] | None = None,
    ):
        self.prefix = prefix
        self._environ = os.environ if environ is None else environ

    def build(self, defaults: Dict[str, Any], baseline: Dict[str, Any]) -> EnvOverrideResult:
        templates = _flatten_dict(defaults or {})
        baseline_values = _flatten_dict(baseline or {})
        paths = sorted(set(templates.keys()) | set(baseline_values.keys()))

        result = EnvOverrideResult()
        for path in paths:
            env_var = self.path_to_env_var(path)
            if env_var not in self._environ:
                continue

            template = templates.get(path, baseline_values.get(path))
            raw_value = self._environ.get(env_var, "")
            try:
                parsed = _parse_value(raw_value, template)
            except ValueError as exc:
                result.errors[path] = f"{env_var}: {exc}"
                continue

            _set_by_path(result.overrides, path.split("."), parsed)
            result.locked_paths[path] = env_var

        return result

    def path_to_env_var(self, path: str) -> str:
        segments = [seg for seg in path.split(".") if seg]
        normalized = [self._normalize_segment(seg) for seg in segments]
        return self.prefix + "__".join(normalized)

    @staticmethod
    def _normalize_segment(segment: str) -> str:
        cleaned = _ENV_SEGMENT_PATTERN.sub("_", segment.upper()).strip("_")
        return cleaned or "UNKNOWN"


def filter_locked_config(
    new_config: Dict[str, Any], locked_paths: Mapping[str, str] | set[str]
) -> tuple[Dict[str, Any], list[str]]:
    """删除被环境变量锁定的配置项，返回过滤结果和被忽略的路径。"""

    if not isinstance(new_config, dict):
        return {}, []

    locked = set(locked_paths.keys()) if isinstance(locked_paths, Mapping) else set(locked_paths)
    flat_new = _flatten_dict(new_config)

    filtered: Dict[str, Any] = {}
    ignored: list[str] = []

    for path, value in flat_new.items():
        if path in locked:
            ignored.append(path)
            continue
        _set_by_path(filtered, path.split("."), deepcopy(value))

    return filtered, sorted(ignored)


def _flatten_dict(data: Dict[str, Any], parent: Sequence[str] | None = None) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {}

    parent_path = list(parent or [])
    out: Dict[str, Any] = {}
    for key, value in data.items():
        key_str = str(key)
        current = [*parent_path, key_str]
        if isinstance(value, dict):
            out.update(_flatten_dict(value, current))
        else:
            out[".".join(current)] = value
    return out


def _set_by_path(target: Dict[str, Any], segments: Sequence[str], value: Any):
    if not segments:
        return
    cursor = target
    for segment in segments[:-1]:
        node = cursor.get(segment)
        if not isinstance(node, dict):
            node = {}
            cursor[segment] = node
        cursor = node
    cursor[segments[-1]] = value


def _parse_value(raw: str, template: Any) -> Any:
    text = raw.strip()

    if isinstance(template, bool):
        lowered = text.lower()
        if lowered in _TRUE_VALUES:
            return True
        if lowered in _FALSE_VALUES:
            return False
        raise ValueError("布尔值仅支持 true/false/1/0/yes/no/on/off")

    if isinstance(template, int) and not isinstance(template, bool):
        try:
            return int(text)
        except ValueError as exc:
            raise ValueError("应为整数") from exc

    if isinstance(template, float):
        try:
            return float(text)
        except ValueError as exc:
            raise ValueError("应为数字") from exc

    if isinstance(template, list):
        parsed = _parse_json_value(text)
        if isinstance(parsed, list):
            return parsed
        if text == "":
            return []
        return [item.strip() for item in text.split(",") if item.strip()]

    if isinstance(template, dict):
        parsed = _parse_json_value(text)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("应为 JSON 对象")

    return raw


def _parse_json_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return None


__all__ = [
    "DEFAULT_ENV_PREFIX",
    "EnvConfigOverlay",
    "EnvOverrideResult",
    "filter_locked_config",
]
