import importlib
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

PLUGIN_DIR = Path.home() / ".openmanus" / "plugins"
PLUGIN_INDEX = PLUGIN_DIR / "index.json"


def _ensure_dir():
    PLUGIN_DIR.mkdir(parents=True, exist_ok=True)


def _load_index() -> dict:
    _ensure_dir()
    if PLUGIN_INDEX.exists():
        try:
            with open(PLUGIN_INDEX) as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception):
            pass
    return {"plugins": {}}


def _save_index(data: dict):
    _ensure_dir()
    with open(PLUGIN_INDEX, "w") as f:
        json.dump(data, f, indent=2)


def list_plugins() -> List[dict]:
    data = _load_index()
    plugins = data.get("plugins", {})
    result = []
    for name, info in plugins.items():
        result.append({
            "name": name,
            "description": info.get("description", ""),
            "version": info.get("version", "0.1.0"),
            "enabled": info.get("enabled", True),
            "path": info.get("path", ""),
        })
    return result


def install_plugin(module_spec: str) -> tuple[bool, str]:
    _ensure_dir()

    if module_spec.startswith(("http://", "https://", "git+")):
        return False, "Remote plugin installation not yet supported. Use local module path."

    module_spec = module_spec.replace("-", "_").replace("/", ".")

    try:
        mod = importlib.import_module(module_spec)
    except ImportError:
        return False, f"Cannot import module '{module_spec}'. Ensure it's installed."

    plugin_name = module_spec.split(".")[-1]
    plugin_info = {
        "description": getattr(mod, "__doc__", "") or "",
        "version": getattr(mod, "__version__", "0.1.0"),
        "enabled": True,
        "path": getattr(mod, "__file__", ""),
    }

    data = _load_index()
    data.setdefault("plugins", {})[plugin_name] = plugin_info
    _save_index(data)

    if plugin_info["path"] and plugin_info["path"] not in sys.path:
        sys.path.insert(0, str(Path(plugin_info["path"]).parent))

    return True, f"Plugin '{plugin_name}' installed successfully."


def remove_plugin(name: str) -> tuple[bool, str]:
    data = _load_index()
    plugins = data.get("plugins", {})
    if name not in plugins:
        return False, f"Plugin '{name}' not found."
    del plugins[name]
    _save_index(data)
    return True, f"Plugin '{name}' removed."


def get_plugin(name: str) -> Optional[dict]:
    data = _load_index()
    return data.get("plugins", {}).get(name)


def load_plugins() -> Dict[str, object]:
    data = _load_index()
    plugins = data.get("plugins", {})
    loaded = {}
    for name, info in plugins.items():
        if not info.get("enabled", True):
            continue
        if info.get("path"):
            path = Path(info["path"])
            if path.parent not in sys.path:
                sys.path.insert(0, str(path.parent))
        try:
            mod = importlib.import_module(name)
            loaded[name] = mod
        except ImportError:
            pass
    return loaded
