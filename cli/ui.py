import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path
from threading import Thread

try:
    from rich.console import Console as RichConsole, Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.syntax import Syntax
    from rich.markdown import Markdown
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
    from rich.text import Text
    from rich.layout import Layout
    from rich.live import Live
    from rich.columns import Columns
    from rich.rule import Rule
    from rich import box
    from rich.style import Style
    from rich.color import Color
    from rich.prompt import Prompt, Confirm
    from rich.tree import Tree
    from rich.align import Align

    RICH_AVAILABLE = True
    console = RichConsole()
except ImportError:
    RICH_AVAILABLE = False

    class StubConsole:
        def print(self, *args, **kwargs):
            print(*args)
        def input(self, prompt=""):
            return input(prompt)

    console = StubConsole()
    Prompt = None
    Confirm = None

BANNER = r"""
   ⠀                                ▄
   █▀▀█ █▀▀█ █▀▀█ █▀▀▄ █▀▀▀ █▀▀█ █▀▀█ █▀▀█
   █  █ █  █ █▀▀▀ █  █ █    █  █ █  █ █▀▀▀
   ▀▀▀▀ █▀▀▀ ▀▀▀▀ ▀  ▀ ▀▀▀▀ ▀▀▀▀ ▀▀▀▀ ▀▀▀▀
"""


def print_banner(mini=False):
    version = "0.2.0"
    if mini:
        if RICH_AVAILABLE:
            console.print(f"> v{version}")
        else:
            print(f"> v{version}")
        return

    if RICH_AVAILABLE:
        console.print(Text(BANNER, style=""))
        console.print(f"openmanus v{version}\n")
    else:
        print(BANNER)
        print(f"openmanus v{version}\n")


def print_step(message: str, step: int = None, total: int = None):
    prefix = f"[{step}/{total}] " if step and total else ""
    if RICH_AVAILABLE:
        console.print(f"  {prefix}{message}", style="yellow")
    else:
        print(f"  {prefix}{message}")


def print_thinking(content: str, mini=False):
    if RICH_AVAILABLE and not mini:
        preview = content[:200].replace("\n", " ") + ("..." if len(content) > 200 else "")
        console.print(f"  {preview}", style="dim")
    elif mini:
        preview = content[:120] + "..." if len(content) > 120 else content
        if RICH_AVAILABLE:
            console.print(f"  [dim]{'─'*4}[/] [blue]thought:[/] {preview}")
        else:
            print(f"  --- thought: {preview}")


def print_tool_call(name: str, arguments: str, mini=False):
    if RICH_AVAILABLE:
        args_preview = arguments[:80] + "..." if len(arguments) > 80 else arguments
        console.print(f"  > {name} {args_preview}", style="dim")
    else:
        print(f"  > {name} {arguments[:80]}")


def print_tool_result(result: str, mini=False):
    if RICH_AVAILABLE:
        preview = result[:100] + "..." if len(result) > 100 else result
        console.print(f"  {preview}", style="dim")
    else:
        print(f"  {result[:100]}")


def print_info(message: str):
    print(f"  {message}")


def print_warning(message: str):
    print(f"  {message}")


def print_error(message: str):
    print(f"  {message}")


def print_done(message: str):
    print(f"\n  {message}")


def print_config_table(config_data: dict):
    _print_kv_table("Configuration", config_data, ("Key", "Value"))


def _print_kv_table(title: str, data: dict, headers: tuple):
    if not RICH_AVAILABLE:
        print(f"\n{title}:")
        for k, v in data.items():
            print(f"  {k}: {v}")
        return

    table = Table(title=title, box=box.SIMPLE, border_style="dim")
    table.add_column(headers[0], style="bold")
    table.add_column(headers[1], style="")
    for k, v in data.items():
        if isinstance(v, dict):
            for sk, sv in v.items():
                val = str(sv) if sv is not None else "<not set>"
                if "key" in sk.lower() and sv and sv != "<not set>":
                    val = "****" + str(sv)[-4:]
                table.add_row(f"{k}.{sk}", val)
        else:
            val = str(v) if v is not None else "<not set>"
            if "key" in k.lower() and v and val != "<not set>":
                val = "****" + str(v)[-4:]
            table.add_row(k, val)
    console.print(table)


def print_sessions_table(sessions: list):
    if not sessions:
        print("No sessions found.")
        return

    header = f"{'Session ID':<24} {'Title':<50} {'Updated'}"
    print(header)
    print("\u2500" * len(header))
    for s in sessions:
        sid = s["id"][:8]
        raw = s.get("preview", "")
        title = raw[:48].replace("\n", " ") if raw else "New session"
        updated = s.get("created_at", "").replace("T", " ")[:19]
        print(f"{sid:<24} {title:<50} {updated}")


def print_models_table(models: list):
    if not RICH_AVAILABLE:
        print("\nModels:")
        for name, info in models:
            print(f"  {name}: {info.get('model', '')}")
        return

    table = Table(box=box.SIMPLE, border_style="dim")
    table.add_column("Name", style="bold")
    table.add_column("Model", style="")
    table.add_column("Base URL", style="dim")
    table.add_column("API Key", style="")
    for name, info in models:
        key_display = "****" + str(info.get("api_key", ""))[-4:] if info.get("api_key") else "<not set>"
        table.add_row(name, str(info.get("model", "")), str(info.get("base_url", "")), key_display)
    console.print(table)


def print_providers_table(providers: list):
    if not RICH_AVAILABLE:
        print("\nProviders:")
        for p in providers:
            print(f"  {p['name']}: {p.get('model', '')}")
        return

    from pathlib import Path
    cred_path = str(Path.home() / ".openmanus" / "providers.json")
    print()
    print(f"\u250c  Credentials", f"{cred_path}")
    print("\u2502")
    if providers:
        for p in providers:
            name = p["name"]
            model = p.get("model", "")
            key = "****" + str(p.get("api_key", ""))[-4:] if p.get("api_key") else ""
            default = " (default)" if p.get("is_default") else ""
            print(f"\u2502  {name:<14} {model[:28]:<28} {key:<10}{default}")
    else:
        print("\u2502  No credentials configured")
    print(f"\u2514  {len(providers)} credential(s)")


def _ul(inner_w):
    return "\u250c" + "\u2500" * inner_w + "\u2510"


def _ll(inner_w):
    return "\u2514" + "\u2500" * inner_w + "\u2518"


def _sep(inner_w):
    return "\u251c" + "\u2500" * inner_w + "\u2524"


def _row(k, v, inner_w):
    return "\u2502 " + str(k).ljust(inner_w - 4 - len(str(v))) + str(v).rjust(len(str(v))) + " \u2502"


def print_stats_table(stats: dict):
    items = [(k.replace("_", " ").title(), str(v)) for k, v in stats.items()]

    if not RICH_AVAILABLE:
        width = max(len(k) + len(v) for k, v in items) + 6 if items else 40
        inner_w = width - 2
        print(_ul(inner_w))
        for k, v in items:
            row = "\u2502 " + k + " " * (inner_w - 3 - len(k) - len(v)) + v + " \u2502"
            print(row)
        print(_ll(inner_w))
        return

    inner_w = 48
    print(_ul(inner_w))
    print("\u2502" + " STATISTICS ".center(inner_w) + "\u2502")
    print(_sep(inner_w))
    for k, v in items:
        pad = inner_w - 3 - len(k) - len(v)
        if pad < 1:
            pad = 1
        print("\u2502 " + k + " " * pad + v + " \u2502")
    print(_ll(inner_w))


def print_agents_table(agents: list):
    if not RICH_AVAILABLE:
        print("\nAgents:")
        for a in agents:
            print(f"  {a['name']}: {a.get('description', '')}")
        return

    table = Table(box=box.SIMPLE, border_style="dim")
    table.add_column("Name", style="bold")
    table.add_column("Description", style="")
    table.add_column("Default", style="")
    for a in agents:
        table.add_row(a["name"], a.get("description", ""), "yes" if a.get("is_default") else "")
    console.print(table)


def print_debug_info(info: dict):
    for k, v in info.items():
        if isinstance(v, dict):
            print(f"{k}:")
            for sk, sv in v.items():
                print(f"  {sk}: {sv}")
        elif isinstance(v, list):
            print(f"{k}:")
            for item in v:
                print(f"- {item}")
        else:
            print(f"{k}: {v}")


def print_export_result(session_id: str, path: str):
    if RICH_AVAILABLE:
        console.print(f"[green]Exported session [bold]{session_id[:8]}[/] to[/]\n[cyan]{path}[/]")
    else:
        print(f"Exported session {session_id[:8]} to {path}")


SLASH_COMMANDS_HELP = [
    ("/help", "Show available slash commands"),
    ("/new", "Start a new session"),
    ("/pick", "Interactive session picker"),
    ("/sessions", "List all sessions"),
    ("/exit", "Exit OpenManus"),
    ("/clear", "Clear the terminal screen"),
    ("/models", "List configured models"),
    ("/agent", "Show current agent info"),
    ("/agents", "List available sub-agents"),
    ("/skill", "List or load a skill"),
    ("/connect", "Add a new provider"),
    ("/export", "Export session as JSON"),
    ("/compact", "Summarize conversation"),
    ("/stats", "Show usage statistics"),
]


def _setup_readline():
    try:
        import readline
        import rlcompleter

        def completer(text, state):
            if text.startswith("/"):
                matches = [c for c, _ in SLASH_COMMANDS_HELP if c.startswith(text)]
                return matches[state] if state < len(matches) else None
            return None

        readline.set_completer(completer)
        readline.parse_and_bind("tab: complete")
    except ImportError:
        pass


def input_with_prompt(prompt: str = ">", allow_empty=False) -> str:
    try:
        result = input(f"> ")
    except (EOFError, KeyboardInterrupt):
        return ""

    if result.startswith("/"):
        cmds = [c for c, _ in SLASH_COMMANDS_HELP]
        matches = [c for c in cmds if c.startswith(result)]
        if result == "/":
            print()
            for cmd, desc in SLASH_COMMANDS_HELP:
                print(f"  {cmd:<16} {desc}")
            print()
        elif len(matches) == 1:
            result = matches[0]
        elif len(matches) > 1:
            print()
            for c in matches:
                desc = next(d for cmd, d in SLASH_COMMANDS_HELP if cmd == c)
                print(f"  {c:<16} {desc}")
            print()

    return result


def confirm_action(message: str, default: bool = True) -> bool:
    if RICH_AVAILABLE and Confirm:
        try:
            return Confirm.ask(f"[yellow]{message}[/]", default=default)
        except (EOFError, KeyboardInterrupt):
            return False
    try:
        default_str = "Y/n" if default else "y/N"
        response = input(f"{message} ({default_str}): ").strip().lower()
        if not response:
            return default
        return response[0] == "y"
    except (EOFError, KeyboardInterrupt):
        return False


def format_json(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)
