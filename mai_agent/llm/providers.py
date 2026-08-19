"""LLM Provider 注册表 — 对齐 DeepSeek Harness 的 provider 抽象（轻量自研版）。

设计（参考 dsh-llm 的 LlmRuntime / provider 管理 UI）:
  - Provider = 一个 LLM 端点（base_url + api_key + 协议 + 模型目录 + 默认模型）
  - 内置 provider（deepseek/openai/moonshot/ollama）可配 key、可改模型目录
  - 自定义 provider 持久化到 ~/.mai/providers.json（用户级，可 CRUD）
  - api_key 优先级: providers.json 里存的 key > provider 专属环境变量 > 默认继承
  - discover_models() → 调端点拉真实模型列表，保存进模型目录
  - 协议: openai-completions（OpenAI 兼容，当前唯一支持调用）；其余协议可配置但调用会提示不支持

配置:
  - LLM_PROVIDER   当前激活的 provider 名（默认 deepseek）
  - LLM_API_KEY    当前 provider 的 key（向后兼容旧 .env）
  - LLM_BASE_URL   当前 provider 的 base_url
  - LLM_MODEL      当前模型
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 用户级 provider 持久化文件（自定义 provider + 内置 provider 的 key/模型目录覆盖）
PROVIDERS_FILE = Path.home() / ".mai" / "providers.json"

# 内置 provider 定义（无需 key 也能列出；key 从 providers.json / 环境变量 / .env 读取）
BUILTIN_PROVIDERS: dict[str, dict[str, Any]] = {
    "deepseek": {
        "name": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "protocol": "openai-completions",
        "models": ["deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"],
        "default_model": "deepseek-v4-pro",
    },
    "openai": {
        "name": "openai",
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "protocol": "openai-completions",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini"],
        "default_model": "gpt-4o-mini",
    },
    "moonshot": {
        "name": "moonshot",
        "label": "Moonshot (Kimi)",
        "base_url": "https://api.moonshot.cn/v1",
        "protocol": "openai-completions",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
        "default_model": "moonshot-v1-32k",
    },
    "ollama": {
        "name": "ollama",
        "label": "Ollama (本地)",
        "base_url": "http://localhost:11434/v1",
        "protocol": "openai-completions",
        "models": [],
        "default_model": "qwen2.5-coder:7b",
    },
}

# 常见协议（调用层目前只支持 openai-completions）
KNOWN_PROTOCOLS = [
    "openai-completions",
    "anthropic-messages",
    "google-gemini",
]

PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")  # 小写字母开头，字母/数字/连字符


@dataclass
class ProviderConfig:
    """单个 provider 的运行时配置。"""
    name: str
    label: str = ""
    base_url: str = ""
    protocol: str = "openai-completions"
    api_key: str = ""
    models: list[str] = field(default_factory=list)
    default_model: str = ""
    is_custom: bool = False  # True = 用户自定义（持久化在 providers.json）
    env_key: str = ""  # provider 专属环境变量名（如 OPENAI_API_KEY）

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "base_url": self.base_url,
            "protocol": self.protocol,
            "api_key": self.api_key,
            "models": self.models,
            "default_model": self.default_model,
            "is_custom": self.is_custom,
            "env_key": self.env_key,
        }


def _env_key_for(name: str) -> str:
    """provider 对应的 API key 环境变量名（OPENAI_API_KEY / MOONSHOT_API_KEY / ...）。"""
    return f"{name.upper()}_API_KEY"


# ── 持久化（~/.mai/providers.json）──────────────────────


def _load_store() -> dict[str, dict[str, Any]]:
    """读 providers.json：{provider_name: spec}。文件不存在返回空 dict。"""
    if not PROVIDERS_FILE.exists():
        return {}
    try:
        data = json.loads(PROVIDERS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data.get("providers", {}) if isinstance(data.get("providers"), dict) else data
    except Exception as exc:
        logger.warning("providers.json 解析失败: %s", exc)
    return {}


def _save_store(store: dict[str, dict[str, Any]]) -> None:
    """写 providers.json。"""
    PROVIDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROVIDERS_FILE.write_text(
        json.dumps({"providers": store}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _store_spec(name: str) -> Optional[dict[str, Any]]:
    """读某个 provider 的持久化 spec（key / models 覆盖）。"""
    return _load_store().get(name)


def upsert_provider(name: str, spec: dict[str, Any]) -> ProviderConfig:
    """创建或更新一个 provider（自定义或覆盖内置的 key/models）。写持久化文件。"""
    if not PROVIDER_ID_RE.match(name):
        raise ValueError("Provider ID 必须以小写字母开头，只能包含小写字母/数字/连字符")
    store = _load_store()
    merged = dict(store.get(name, {}))
    # 只更新传入的非空字段（label/base_url/protocol/api_key/models 等）
    for key in ("label", "base_url", "protocol", "api_key", "models", "default_model"):
        if key in spec and spec[key] is not None and spec[key] != "":
            merged[key] = spec[key]
    store[name] = merged
    _save_store(store)
    return resolve_provider(name)  # type: ignore[return-value]


def delete_provider(name: str) -> bool:
    """删除自定义 provider（内置 provider 的覆盖记录也删，回到默认）。"""
    store = _load_store()
    if name not in store:
        return False
    del store[name]
    _save_store(store)
    return True


# ── 构造 / 列举 ─────────────────────────────────────────


def _build_provider(name: str, spec: dict[str, Any], cfg: Any) -> ProviderConfig:
    """按 spec 构造 ProviderConfig。

    key 来源（按优先级）:
      1. providers.json 持久化的 api_key（用户 UI 里填的）
      2. provider 专属环境变量（OPENAI_API_KEY / ...）
      3. 仅 deepseek（默认 provider）：继承 cfg.llm_api_key（.env 的 LLM_API_KEY）
    其他内置 provider 不继承——没有 key 就是未配置，避免误发。
    """
    stored = _store_spec(name) or {}
    api_key = stored.get("api_key") or os.environ.get(_env_key_for(name), "")
    if not api_key and name == "deepseek":
        api_key = cfg.llm_api_key or ""
    base_url = stored.get("base_url") or spec.get("base_url") or cfg.llm_base_url or ""
    protocol = stored.get("protocol") or spec.get("protocol") or "openai-completions"
    models = [str(m) for m in (stored.get("models") or spec.get("models") or [])]
    default_model = str(stored.get("default_model") or spec.get("default_model") or
                        (models[0] if models else ""))
    is_custom = name not in BUILTIN_PROVIDERS
    return ProviderConfig(
        name=name,
        label=str(stored.get("label") or spec.get("label", name)),
        base_url=base_url,
        protocol=protocol,
        api_key=api_key,
        models=models,
        default_model=default_model,
        is_custom=is_custom,
        env_key=_env_key_for(name),
    )


def list_providers() -> list[ProviderConfig]:
    """列出所有 provider（内置 + 自定义 + 持久化覆盖）。"""
    cfg = _current_config()
    providers: list[ProviderConfig] = []
    seen: set[str] = set()

    for name, spec in BUILTIN_PROVIDERS.items():
        seen.add(name)
        providers.append(_build_provider(name, spec, cfg))

    store = _load_store()
    for name, spec in store.items():
        if name in seen:
            continue  # 内置的覆盖已由 _build_provider 处理
        seen.add(name)
        providers.append(_build_provider(name, spec, cfg))

    return providers


def resolve_provider(name: str) -> Optional[ProviderConfig]:
    """按名字解析 provider；不存在返回 None。"""
    for p in list_providers():
        if p.name == name:
            return p
    return None


def _current_config() -> Any:
    """获取全局 Config（延迟 import 避免循环依赖）。"""
    from mai_agent.config import get_config
    return get_config()


def current_provider() -> ProviderConfig:
    """当前激活的 provider（LLM_PROVIDER 指定，默认 deepseek）。"""
    from mai_agent.config import get_config
    cfg = get_config()
    name = cfg.llm_provider or "deepseek"
    p = resolve_provider(name)
    if p is None:
        p = _build_provider("deepseek", BUILTIN_PROVIDERS["deepseek"], cfg)
        p.name = name
    if cfg.llm_base_url and not _store_spec(name):
        p.base_url = cfg.llm_base_url
    if cfg.llm_api_key and not _store_spec(name) and not os.environ.get(p.env_key):
        p.api_key = cfg.llm_api_key
    active_model = cfg.llm_model or p.default_model
    p.default_model = active_model
    if active_model and active_model not in p.models:
        p.models = [active_model] + [m for m in p.models if m != active_model]
    return p


# ── 模型目录 ────────────────────────────────────────────


async def discover_models(provider: ProviderConfig) -> list[str]:
    """调 provider 端点 /v1/models 拉取真实可用模型列表（对齐 dsh discoverModels）。

    仅 openai-completions 协议支持端点发现；失败回退到已有目录。
    """
    if provider.protocol != "openai-completions":
        return provider.models
    if not provider.base_url or not provider.api_key:
        return provider.models
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{provider.base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {provider.api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
            models = [str(m.get("id", "")) for m in data.get("data", []) if m.get("id")]
            if models:
                return sorted(models)
    except Exception as exc:
        logger.warning("discover_models(%s) 失败，回退目录: %s", provider.name, exc)
    return provider.models


def save_models(provider_name: str, models: list[str], default_model: str = "") -> None:
    """把模型目录持久化到 providers.json（发现结果或手动添加后调用）。"""
    store = _load_store()
    entry = dict(store.get(provider_name, {}))
    entry["models"] = [str(m) for m in models]
    if default_model:
        entry["default_model"] = default_model
    store[provider_name] = entry
    _save_store(store)


def add_model(provider_name: str, model: str) -> None:
    """手动添加一个模型到目录（去重）。"""
    if not model or not model.strip():
        return
    store = _load_store()
    entry = dict(store.get(provider_name, {}))
    models = [str(m) for m in entry.get("models", [])]
    if model not in models:
        models.append(model)
    entry["models"] = models
    if not entry.get("default_model"):
        entry["default_model"] = model
    store[provider_name] = entry
    _save_store(store)
