import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def get_system_info() -> dict:
    return {
        "OS": f"{platform.system()} {platform.release()}",
        "Platform": platform.platform(),
        "Python": sys.version,
        "Python Executable": sys.executable,
        "Hostname": platform.node(),
        "CPU": platform.processor() or "unknown",
    }


def get_env_info() -> dict:
    relevant_vars = [
        "PATH",
        "HOME",
        "SHELL",
        "TERM",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENMANUS_DIR",
    ]
    result = {}
    for var in relevant_vars:
        val = os.environ.get(var, "")
        if "API_KEY" in var and val:
            val = val[:8] + "..." if len(val) > 8 else "***"
        result[var] = val if val else "<not set>"
    return result


def get_config_info() -> dict:
    try:
        from app.config import config as app_config
        llm = app_config.llm
        models = {}
        for name, settings in llm.items():
            models[name] = {
                "model": settings.model,
                "base_url": settings.base_url,
                "api_key": settings.api_key[:8] + "..." if settings.api_key else "<not set>",
                "max_tokens": settings.max_tokens,
            }
        return {
            "Config file": str(app_config._get_config_path()),
            "Workspace": str(app_config.workspace_root),
            "Models": models,
            "Sandbox": str(app_config.sandbox.use_sandbox),
        }
    except Exception as e:
        return {"Error": f"Cannot load config: {e}"}


def get_network_info() -> dict:
    result = {}
    try:
        import httpx
        r = httpx.get("https://httpbin.org/ip", timeout=5)
        result["Public IP"] = r.json().get("origin", "unknown")
    except Exception:
        result["Public IP"] = "unreachable"

    result["Proxy"] = os.environ.get("HTTP_PROXY", os.environ.get("HTTPS_PROXY", "<none>"))
    return result


def check_dependencies() -> list:
    required = [
        "pydantic", "openai", "loguru", "rich", "httpx",
    ]
    results = []
    for mod in required:
        try:
            importlib = __import__("importlib")
            spec = importlib.util.find_spec(mod) if hasattr(importlib, "util") else None
            if mod in sys.modules:
                ver = getattr(sys.modules[mod], "__version__", "installed")
                results.append({"name": mod, "status": "ok", "version": ver})
            elif spec:
                results.append({"name": mod, "status": "ok", "version": "found"})
            else:
                results.append({"name": mod, "status": "missing", "version": ""})
        except Exception:
            results.append({"name": mod, "status": "error", "version": ""})
    return results


def collect_debug_info() -> dict:
    info = {
        "System": get_system_info(),
        "Environment": get_env_info(),
        "Configuration": get_config_info(),
        "Dependencies": check_dependencies(),
    }
    try:
        info["Network"] = get_network_info()
    except Exception:
        info["Network"] = {"Error": "Could not check network"}
    return info
