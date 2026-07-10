import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from copy import deepcopy

CONFIG_DIR = Path.home() / ".openmanus"
PROVIDERS_FILE = CONFIG_DIR / "providers.json"


def _ensure_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _load_providers() -> dict:
    _ensure_dir()
    if PROVIDERS_FILE.exists():
        try:
            with open(PROVIDERS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception):
            pass
    return {"providers": {}, "default": None}


def _save_providers(data: dict):
    _ensure_dir()
    with open(PROVIDERS_FILE, "w") as f:
        json.dump(data, f, indent=2)


KNOWN_PROVIDERS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "models": ["claude-3-7-sonnet-20250219", "claude-3-5-sonnet-20241022", "claude-3-opus-20240229"],
    },
    "google": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "models": ["gemini-2.0-flash", "gemini-2.0-pro"],
    },
    "azure": {
        "base_url": "https://YOUR_RESOURCE.openai.azure.com",
        "models": ["gpt-4o", "gpt-4"],
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "models": ["llama3", "mistral", "codellama"],
    },
    "ppio": {
        "base_url": "https://api.ppio.ai/v1",
        "models": ["gpt-4o", "claude-3-5-sonnet"],
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "models": ["mistral-large-latest", "mistral-medium"],
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["llama3-70b-8192", "llama3-8b-8192"],
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "models": ["meta-llama/Llama-3-70b-chat-hf"],
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "models": ["anthropic/claude-3.5-sonnet", "openai/gpt-4o"],
    },
    "custom": {
        "base_url": "",
        "models": [],
    },
}


def list_providers() -> List[dict]:
    data = _load_providers()
    configured = data.get("providers", {})
    default_name = data.get("default")

    result = []
    for name, info in configured.items():
        entry = {
            "name": name,
            "model": info.get("model", ""),
            "base_url": info.get("base_url", ""),
            "api_key": info.get("api_key", "")[-8:] if info.get("api_key") else "",
            "is_default": name == default_name,
        }
        result.append(entry)

    if not result:
        for name, info in KNOWN_PROVIDERS.items():
            result.append({
                "name": name,
                "model": info["models"][0] if info["models"] else "",
                "base_url": info["base_url"],
                "api_key": "",
                "is_default": False,
            })

    return result


def add_provider(name: str, model: str, base_url: str, api_key: str, set_default: bool = False) -> bool:
    data = _load_providers()
    data.setdefault("providers", {})
    data["providers"][name] = {
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
    }
    if set_default or not data.get("default"):
        data["default"] = name
    _save_providers(data)
    return True


def remove_provider(name: str) -> bool:
    data = _load_providers()
    providers = data.get("providers", {})
    if name not in providers:
        return False
    del providers[name]
    if data.get("default") == name:
        data["default"] = next(iter(providers.keys())) if providers else None
    _save_providers(data)
    return True


def set_default_provider(name: str) -> bool:
    data = _load_providers()
    if name not in data.get("providers", {}):
        return False
    data["default"] = name
    _save_providers(data)
    return True


def get_provider(name: str) -> Optional[dict]:
    data = _load_providers()
    return data.get("providers", {}).get(name)


def get_default_provider() -> Optional[str]:
    data = _load_providers()
    return data.get("default")


def sync_to_config():
    """Sync providers to OpenManus config.toml"""
    from app.config import config as app_config

    data = _load_providers()
    providers = data.get("providers", {})
    default = data.get("default")

    if not providers:
        return

    config_path = app_config.root_path / "config" / "config.toml"
    if not config_path.exists():
        return

    try:
        import tomllib
        with open(config_path, "rb") as f:
            cfg = tomllib.load(f)
    except Exception:
        return

    changed = False
    for name, info in providers.items():
        toml_key = name.lower()
        if toml_key not in cfg.get("llm", {}):
            cfg.setdefault("llm", {})[toml_key] = {}
        llm_entry = cfg["llm"][toml_key]
        if isinstance(llm_entry, dict):
            if info.get("model"):
                llm_entry["model"] = info["model"]
            if info.get("base_url"):
                llm_entry["base_url"] = info["base_url"]
            if info.get("api_key"):
                llm_entry["api_key"] = info["api_key"]
            changed = True

    if default and default in providers:
        d = providers[default]
        llm = cfg.setdefault("llm", {})
        for k in ("model", "base_url", "api_key"):
            if d.get(k):
                llm[k] = d[k]
        changed = True

    if changed:
        try:
            import tomli_w
            with open(config_path, "wb") as f:
                tomli_w.dump(cfg, f)
        except ImportError:
            pass


def add_opencode_provider(provider_spec: str) -> tuple[bool, str]:
    """Parse opencode-style provider string: provider_name or provider_name=model"""
    if "=" in provider_spec:
        name, model = provider_spec.split("=", 1)
    else:
        name = provider_spec
        model = ""

    name = name.strip().lower()

    if name in KNOWN_PROVIDERS:
        info = KNOWN_PROVIDERS[name]
        add_provider(
            name=name,
            model=model or info["models"][0],
            base_url=info["base_url"],
            api_key="",
            set_default=False,
        )
        return True, f"Added provider '{name}' configured with model '{model or info['models'][0]}'"

    return False, f"Unknown provider '{name}'. Known: {', '.join(KNOWN_PROVIDERS.keys())}"
