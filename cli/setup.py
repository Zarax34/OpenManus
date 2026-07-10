import os
import shutil
from pathlib import Path

from cli.ui import (
    RICH_AVAILABLE, console, print_banner, print_info,
    print_warning, print_error, print_done, input_with_prompt,
    confirm_action,
)
from cli.providers import KNOWN_PROVIDERS

try:
    from rich.prompt import Prompt, Confirm
except ImportError:
    Prompt = None
    Confirm = None

SETUP_MARKER = "# OpenManus configuration"


def is_first_run() -> bool:
    """Check if this is the first run (no config or placeholder API keys)"""
    from app.config import PROJECT_ROOT

    config_dir = PROJECT_ROOT / "config"
    config_path = config_dir / "config.toml"
    example_path = config_dir / "config.example.toml"

    if not config_path.exists() and not example_path.exists():
        return True

    try:
        import tomllib
        path = config_path if config_path.exists() else example_path
        with open(path, "rb") as f:
            cfg = tomllib.load(f)
    except Exception:
        return True

    llm = cfg.get("llm", {})
    if isinstance(llm, dict) and llm.get("api_key") and llm["api_key"] != "YOUR_API_KEY":
        return False

    if not config_path.exists():
        return True

    return True


def run_setup():
    """First-run setup wizard"""
    from app.config import PROJECT_ROOT

    print_banner()
    print_info("Welcome to OpenManus! Let's get you set up.\n")

    config_dir = PROJECT_ROOT / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.toml"

    if config_path.exists():
        ans = input_with_prompt("Config file exists. Overwrite? (y/N)")
        if ans.lower() not in ("y", "yes"):
            print_info("Setup cancelled.")
            return

    provider_names = list(KNOWN_PROVIDERS.keys())
    print_info("Choose your AI provider:")
    for i, name in enumerate(provider_names, 1):
        info = KNOWN_PROVIDERS[name]
        models = ", ".join(info["models"][:3])
        print_info(f"  {i}. {name} ({models}...)")

    choice = input_with_prompt(f"Provider [1-{len(provider_names)}]")
    try:
        idx = int(choice) - 1
        provider_name = provider_names[idx]
    except (ValueError, IndexError):
        provider_name = "openai"
        print_info(f"Using default: {provider_name}")

    provider = KNOWN_PROVIDERS[provider_name]

    print_info(f"\nConfiguring [bold cyan]{provider_name}[/]")

    if RICH_AVAILABLE:
        base_url = Prompt.ask("  API Base URL", default=provider["base_url"])
    else:
        default = provider["base_url"]
        base_url = input(f"  API Base URL [{default}]: ") or default

    model_names = provider["models"]
    if model_names:
        print_info("  Available models:")
        for i, m in enumerate(model_names, 1):
            print_info(f"    {i}. {m}")
        if RICH_AVAILABLE:
            model = Prompt.ask("  Model", default=model_names[0])
        else:
            default = model_names[0]
            model = input(f"  Model [{default}]: ") or default
    else:
        if RICH_AVAILABLE:
            model = Prompt.ask("  Model name", default="gpt-4o")
        else:
            model = input("  Model name [gpt-4o]: ") or "gpt-4o"

    env_var = f"{provider_name.upper()}_API_KEY"
    env_key = os.environ.get(env_var, "")
    if env_key:
        print_info(f"  Found ${env_var} in environment")
        api_key = env_key
    else:
        if RICH_AVAILABLE:
            api_key = Prompt.ask("  API Key", password=True)
        else:
            api_key = input("  API Key: ")

    if not api_key:
        print_error("API key is required.")
        return

    max_tokens = "8192"
    if RICH_AVAILABLE:
        max_tokens = Prompt.ask("  Max tokens", default="8192")
    else:
        max_tokens = input("  Max tokens [8192]: ") or "8192"

    temperature = "0.0"
    if RICH_AVAILABLE:
        temperature = Prompt.ask("  Temperature (0.0-2.0)", default="0.0")
    else:
        temperature = input("  Temperature (0.0-2.0) [0.0]: ") or "0.0"

    use_vision = False
    if RICH_AVAILABLE:
        use_vision = Confirm.ask("\n  Configure a separate vision model?", default=False)
    else:
        ans = input("\n  Configure separate vision model? (y/N): ").lower()
        use_vision = ans in ("y", "yes")

    setup_vision = ""
    if use_vision:
        vis_model = Prompt.ask("  Vision model", default=model) if RICH_AVAILABLE else (input(f"  Vision model [{model}]: ") or model)
        vis_base_url = Prompt.ask("  Vision API Base URL", default=base_url) if RICH_AVAILABLE else (input(f"  Vision API Base URL [{base_url}]: ") or base_url)
        vis_api_key = Prompt.ask("  Vision API Key", password=True, default=api_key) if RICH_AVAILABLE else (input(f"  Vision API Key [{api_key[:4]}...]: ") or api_key)
        setup_vision = f"""
[llm.vision]
model = "{vis_model}"
base_url = "{vis_base_url}"
api_key = "{vis_api_key}"
max_tokens = {max_tokens}
temperature = {temperature}"""

    config_content = f"""# OpenManus configuration
[llm]
model = "{model}"
base_url = "{base_url}"
api_key = "{api_key}"
max_tokens = {max_tokens}
temperature = {temperature}
{setup_vision}

[mcp]
server_reference = "app.mcp.server"

[runflow]
use_data_analysis_agent = false
"""

    with open(config_path, "w") as f:
        f.write(config_content)

    print_done(f"\nConfiguration saved to {config_path}")

    print_info("\nYou can also set these environment variables:")
    print_info(f"  {env_var}")

    print_info("\nRun [bold]openmanus[/] again to start!")
