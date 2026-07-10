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
    __  ___  ____  __  __  _   _   __  __  _   _   ____
   / / / _ \|  _ \|  \/  || | | | |  \/  || | | | / ___|
  / / | | | | |_) | |\/| || |_| | | |\/| || |_| | \___ \
 / /  | |_| |  __/| |  | ||  _  | | |  | ||  _  |  ___) |
/_/    \___/|_|   |_|  |_||_| |_| |_|  |_||_| |_| |____/
"""


def print_banner(mini=False):
    version = "0.2.0"
    if not RICH_AVAILABLE:
        print(BANNER)
        print(f"OpenManus v{version}")
        return

    if mini:
        console.print(f"[cyan]OpenManus v{version}[/] [dim]type 'exit' to quit[/]")
        return

    banner_text = Text(BANNER, style="bold cyan")
    panel = Panel(
        banner_text,
        subtitle=Text(f"v{version}  |  open-source AI agent", style="dim white"),
        box=box.DOUBLE,
        border_style="cyan",
        padding=(0, 0),
    )
    console.print(panel)


def print_step(message: str, step: int = None, total: int = None):
    prefix = f"[{step}/{total}] " if step and total else ""
    if RICH_AVAILABLE:
        console.print(f"  {prefix}{message}", style="yellow")
    else:
        print(f"  {prefix}{message}")


def print_thinking(content: str, mini=False):
    if not RICH_AVAILABLE:
        print(f"\n--- Thinking ---\n{content}\n----------------\n")
        return

    if mini:
        preview = content[:120] + "..." if len(content) > 120 else content
        console.print(f"  [dim]{'─'*4}[/] [blue]thought:[/] {preview}")
        return

    panel = Panel(
        Markdown(content) if len(content) > 100 else Text(content),
        title="[bold blue]Thought[/]",
        border_style="blue",
        box=box.ROUNDED,
        padding=(1, 2),
    )
    console.print(panel)


def print_tool_call(name: str, arguments: str, mini=False):
    if not RICH_AVAILABLE:
        print(f"\n[Tool: {name}] arguments: {arguments}\n")
        return

    if mini:
        args_preview = arguments[:80] + "..." if len(arguments) > 80 else arguments
        console.print(f"  [dim]{'─'*4}[/] [magenta]tool:[/] [bold]{name}[/] {args_preview}")
        return

    table = Table(
        title=f"[bold magenta]Tool: {name}[/]",
        box=box.SIMPLE,
        border_style="magenta",
        show_header=False,
        title_justify="left",
    )
    table.add_column("Key", style="bold green")
    table.add_column("Value", style="white")
    try:
        args_dict = json.loads(arguments)
        for k, v in args_dict.items():
            val = str(v)
            if len(val) > 80:
                val = val[:77] + "..."
            table.add_row(k, val)
    except (json.JSONDecodeError, TypeError):
        table.add_row("arguments", str(arguments)[:100])
    console.print(table)


def print_tool_result(result: str, mini=False):
    if not RICH_AVAILABLE:
        print(f"\nResult: {result[:300]}{'...' if len(result) > 300 else ''}\n")
        return

    if mini:
        preview = result[:100] + "..." if len(result) > 100 else result
        console.print(f"  [dim]{'─'*4}[/] [green]result:[/] {preview}")
        return

    display = result
    if len(result) > 800:
        display = result[:800] + "\n[dim]... (truncated)[/]"

    syntax = Syntax(display, "python", theme="monokai", word_wrap=True)
    panel = Panel(
        syntax,
        title="[bold green]Result[/]",
        border_style="green",
        box=box.ROUNDED,
    )
    console.print(panel)


def print_info(message: str):
    if RICH_AVAILABLE:
        console.print(f"  {message}", style="green")
    else:
        print(message)


def print_warning(message: str):
    if RICH_AVAILABLE:
        console.print(f"  {message}", style="yellow")
    else:
        print(f"WARNING: {message}")


def print_error(message: str):
    if RICH_AVAILABLE:
        console.print(f"  {message}", style="bold red")
    else:
        print(f"ERROR: {message}")


def print_done(message: str):
    if RICH_AVAILABLE:
        console.print(f"\n  {message}", style="bold green")
    else:
        print(f"\n{message}")


def print_config_table(config_data: dict):
    if not RICH_AVAILABLE:
        print("\nConfiguration:")
        for k, v in config_data.items():
            print(f"  {k}: {v}")
        return

    table = Table(title="Configuration", box=box.ROUNDED, border_style="cyan")
    table.add_column("Key", style="bold yellow")
    table.add_column("Value", style="white")
    for k, v in config_data.items():
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
    if not RICH_AVAILABLE:
        print("\nSessions:")
        for s in sessions:
            print(f"  {s['id'][:8]} | {s.get('created_at', '')} | {s.get('message_count', 0)} msgs")
        return

    table = Table(
        title="Sessions",
        box=box.ROUNDED,
        border_style="blue",
    )
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Created", style="yellow")
    table.add_column("Messages", style="white", justify="right")
    table.add_column("Preview", style="dim white")
    for s in sessions:
        table.add_row(
            s["id"][:8],
            s.get("created_at", ""),
            str(s.get("message_count", 0)),
            s.get("preview", "")[:60],
        )
    console.print(table)


def print_models_table(models: list):
    if not RICH_AVAILABLE:
        print("\nModels:")
        for name, info in models:
            print(f"  {name}: {info.get('model', '')}")
        return

    table = Table(
        title="Configured Models",
        box=box.ROUNDED,
        border_style="green",
    )
    table.add_column("Name", style="bold cyan")
    table.add_column("Model", style="yellow")
    table.add_column("Base URL", style="dim white")
    table.add_column("API Key", style="white")
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

    table = Table(
        title="AI Providers",
        box=box.ROUNDED,
        border_style="cyan",
    )
    table.add_column("Name", style="bold yellow")
    table.add_column("Model", style="cyan")
    table.add_column("Base URL", style="dim white")
    table.add_column("API Key", style="white")
    table.add_column("Default", style="green")
    for p in providers:
        key_display = "****" + str(p.get("api_key", ""))[-4:] if p.get("api_key") else ""
        table.add_row(
            p["name"],
            p.get("model", ""),
            p.get("base_url", ""),
            key_display,
            "yes" if p.get("is_default") else "",
        )
    console.print(table)


def print_stats_table(stats: dict):
    if not RICH_AVAILABLE:
        print("\nUsage Stats:")
        for k, v in stats.items():
            print(f"  {k}: {v}")
        return

    table = Table(title="Usage Statistics", box=box.ROUNDED, border_style="blue")
    table.add_column("Metric", style="bold yellow")
    table.add_column("Value", style="white", justify="right")
    for k, v in stats.items():
        table.add_row(k.replace("_", " ").title(), str(v))
    console.print(table)


def print_agents_table(agents: list):
    if not RICH_AVAILABLE:
        print("\nAgents:")
        for a in agents:
            print(f"  {a['name']}: {a.get('description', '')}")
        return

    table = Table(
        title="Agents",
        box=box.ROUNDED,
        border_style="green",
    )
    table.add_column("Name", style="bold cyan")
    table.add_column("Description", style="white")
    table.add_column("Default", style="green")
    for a in agents:
        table.add_row(a["name"], a.get("description", ""), "yes" if a.get("is_default") else "")
    console.print(table)


def print_debug_info(info: dict):
    if not RICH_AVAILABLE:
        print("\nDebug Info:")
        for k, v in info.items():
            print(f"  {k}: {v}")
        return

    tree = Tree("[bold yellow]Debug Info[/]")
    for k, v in info.items():
        if isinstance(v, dict):
            branch = tree.add(f"[bold]{k}[/]")
            for sk, sv in v.items():
                branch.add(f"[cyan]{sk}:[/] {sv}")
        elif isinstance(v, list):
            branch = tree.add(f"[bold]{k}[/]")
            for item in v:
                branch.add(str(item))
        else:
            tree.add(f"[bold]{k}:[/] {v}")
    console.print(Panel(tree, border_style="yellow", title="Debug"))


def print_export_result(session_id: str, path: str):
    if RICH_AVAILABLE:
        panel = Panel(
            f"[green]Exported session [bold]{session_id[:8]}[/] to[/]\n[cyan]{path}[/]",
            title="Export Complete",
            border_style="green",
        )
        console.print(panel)


class AgentStatusBar:
    def __init__(self):
        self._progress = None
        self._task_id = None
        self._enabled = RICH_AVAILABLE

    def start(self, message="Processing..."):
        if not self._enabled:
            print(f"  {message}")
            return
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            transient=False,
        )
        self._task_id = self._progress.add_task(message, total=None)
        self._progress.__enter__()

    def update(self, message: str):
        if self._progress and self._task_id is not None:
            self._progress.update(self._task_id, description=message)

    def stop(self):
        if self._progress:
            self._progress.__exit__(None, None, None)
            self._progress = None
            self._task_id = None


def input_with_prompt(prompt: str = "Enter your prompt", allow_empty=False) -> str:
    if RICH_AVAILABLE:
        try:
            result = Prompt.ask(f"\n[bold cyan]{prompt}[/]")
            return result
        except (EOFError, KeyboardInterrupt):
            return ""
    try:
        return input(f"\n{prompt}: ")
    except (EOFError, KeyboardInterrupt):
        return ""


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
