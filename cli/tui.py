import asyncio
import os
import shutil
import subprocess
import sys
import time
import json
from datetime import datetime
from typing import Optional

from cli.session import create_session, save_session, list_sessions, delete_session
from cli.stats import usage_stats
from cli.ui import (
    RICH_AVAILABLE, console, print_banner, print_thinking,
    print_tool_call, print_tool_result, print_info, print_warning,
    print_error, print_done, input_with_prompt, confirm_action,
    print_sessions_table,
)

try:
    from rich.live import Live
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.text import Text
    from rich.table import Table
    from rich.rule import Rule
    from rich.syntax import Syntax
    from rich.spinner import Spinner
    from rich import box
    HAVE_LIVE = True
except ImportError:
    HAVE_LIVE = False


SLASH_COMMANDS = {
    "/help": "Show available slash commands",
    "/new": "Start a new session",
    "/exit": "Exit OpenManus",
    "/clear": "Clear the terminal screen",
    "/models": "List configured models",
    "/sessions": "List all sessions",
    "/export": "Export current session as JSON",
    "/compact": "Summarize conversation to save tokens",
    "/agent": "Show current agent info",
    "/connect": "Add a new provider",
    "/stats": "Show usage statistics",
    "/skill": "List or load a skill (/skill <name> to load)",
    "/agents": "List available sub-agents for @mention",
}


def _format_model(model: str) -> str:
    if model and "/" in model:
        parts = model.split("/", 1)
        return parts[1] if parts[0] in ("z-ai",) else model
    return model or "unknown"


async def _handle_slash(cmd: str, args: str, session: "InteractiveSession") -> bool:
    """Handle a slash command. Returns True if the command was handled."""
    match cmd:
        case "/help":
            print("\n  Slash Commands:")
            for name, desc in SLASH_COMMANDS.items():
                print(f"    {name:<20} {desc}")
            print()
            return True

        case "/new":
            session.messages = []
            session.session_id = create_session()
            save_session(session.session_id, session.messages)
            print_info("New session started")
            return True

        case "/exit":
            return False

        case "/clear":
            os.system("clear" if os.name == "posix" else "cls")
            return True

        case "/models":
            from app.config import config
            for name, settings in config.llm.items():
                model = settings.model or "?self._mode"
                url = settings.base_url or ""
                print(f"  {name:<12} {model:<30} {url}")
            return True

        case "/sessions":
            sessions = list_sessions()
            if not sessions:
                print_info("No sessions found.")
            else:
                print_sessions_table(sessions)
            return True

        case "/export":
            from cli.export_import import export_session
            path = export_session(session.session_id)
            if path:
                print_info(f"Exported session {session.session_id[:8]} to {path}")
            else:
                print_error("Session export failed")
            return True

        case "/compact":
            if len(session.messages) < 4:
                print_info("Conversation too short to compact")
                return True
            try:
                from app.schema import Message
                text = "\n".join(
                    m.get("content", "") or ""
                    for m in session.messages
                    if m.get("role") in ("user", "assistant")
                )
                summary = await session.agent.llm.ask(
                    messages=[Message.user_message(
                        f"Summarize this conversation concisely, keeping key details:\n\n{text[-3000:]}"
                    )],
                    stream=False,
                )
                session.messages = [
                    {"role": "user", "content": f"Previous conversation summary:\n{summary}"}
                ]
                print_info("Conversation compacted")
            except Exception as e:
                print_error(f"Compact failed: {e}")
            return True

        case "/agent":
            print_info(f"Agent: {session.agent_name}")
            print_info(f"Model: {_format_model(session._model)}")
            print_info(f"Session: {session.session_id[:8]}")
            print_info(f"Messages: {len(session.messages)}")
            print_info("\nSub-agents (use @name to invoke):")
            from app.tool.task import SUB_AGENTS
            for name, info in SUB_AGENTS.items():
                print(f"  @{name:<12} {info['description']}")
            return True

        case "/agents":
            from app.tool.task import SUB_AGENTS
            print()
            for name, info in SUB_AGENTS.items():
                print(f"  @{name:<12} {info['description']}")
            print()
            print_info("Use @name in your prompt to invoke a sub-agent")
            return True

        case "/connect":
            print_info("Connecting...")
            try:
                from cli.providers import add_provider as _add, KNOWN_PROVIDERS
                name = args or input("  Provider name: ").strip()
                if not name:
                    return True
                if name.lower() in KNOWN_PROVIDERS:
                    info = KNOWN_PROVIDERS[name.lower()]
                    _add(name, info["models"][0] if info["models"] else "", info["base_url"], "", set_default=True)
                else:
                    model = input("  Model: ").strip()
                    url = input("  Base URL: ").strip()
                    key = input("  API key: ").strip()
                    _add(name, model, url, key, set_default=True)
                print_done(f"Provider '{name}' added")
            except Exception as e:
                print_error(f"Connect failed: {e}")
            return True

        case "/stats":
            stats = usage_stats.get_summary()
            for k, v in stats.items():
                print(f"  {k:<22} {v}")
            return True

        case "/skill":
            from app.tool.skill import _discover_skills
            skills = _discover_skills()
            if args:
                for s in skills:
                    if s["name"] == args:
                        print(f"\n--- {s['name']} ---")
                        print(s["description"])
                        print(f"Path: {s['path']}\n")
                        return True
                print_error(f"Skill '{args}' not found")
                return True
            if not skills:
                print_info("No skills found")
                return True
            print()
            for s in skills:
                print(f"  {s['name']:<20} {s['description']}")
            print()
            print_info("Use '/skill <name>' to view a skill's content")
            return True

        case _:
            print_error(f"Unknown command: {cmd}")
            print_info("Type /help for available commands")
            return True


class InteractiveSession:
    def __init__(self, auto_approve: bool = False, mini: bool = False, no_replay: bool = False,
                 agent_name: str = None, model: str = None, pure: bool = False):
        self.auto_approve = auto_approve
        self.mini = mini
        self.no_replay = no_replay
        self.agent_name = agent_name or "Manus"
        self._model = model
        self.pure = pure
        self.session_id = create_session()
        self.messages = []
        self.agent = None
        self.start_time = None

    async def start(self):
        if self.mini:
            console.print(f"[bold]> OpenManus v0.2.0[/] [dim]type 'exit' to quit[/]")
        else:
            print_banner()

        try:
            from app.agent.manus import Manus
            self.agent = await Manus.create()
        except ImportError as e:
            missing = str(e).replace("No module named ", "")
            print_error(f"Missing dependency: {missing}")
            print_info("Install required packages: pip install -r requirements.txt")
            return
        except Exception as e:
            print_error(f"Failed to initialize agent: {e}")
            return

        if not self.mini:
            from app.schema import Message
            try:
                await asyncio.wait_for(
                    self.agent.llm.ask(
                        messages=[Message.user_message("ok")],
                        stream=False,
                    ),
                    timeout=15,
                )
            except asyncio.TimeoutError:
                print_warning("LLM connection timed out. Check config.")
            except Exception as e:
                err = str(e)
                if "401" in err:
                    print_error("Invalid API key. Run: openmanus")
                elif "404" in err or "not found" in err.lower():
                    print_error("Model not found. Check config/config.toml")
                else:
                    print_warning(f"LLM: {err[:80]}")

        self.start_time = time.time()

        try:
            while True:
                prompt = input_with_prompt()
                if prompt.lower() in ("exit", "quit", "q"):
                    break
                if not prompt.strip():
                    continue

                if prompt.startswith("/"):
                    parts = prompt.split(None, 1)
                    cmd = parts[0].lower()
                    args = parts[1] if len(parts) > 1 else ""
                    handled = await _handle_slash(cmd, args, self)
                    if not handled:
                        break
                    continue

                if "@" in prompt:
                    from app.tool.task import SUB_AGENTS
                    for name in SUB_AGENTS:
                        mention = f"@{name}"
                        if mention in prompt:
                            task_prompt = prompt.replace(mention, "").strip()
                            print_info(f"Invoking sub-agent @{name}...")
                            result = await _handle_slash("/skill" if name == "skill" else "", "", self)
                            from app.tool.task import Task
                            t = Task()
                            res = await t.execute(prompt=task_prompt or "Handle this task", agent=name)
                            print(f"\n  @{name} result:\n{res}\n")
                            self.messages.append({"role": "user", "content": prompt})
                            self.messages.append({"role": "assistant", "content": f"[@{name}]: {res}"})
                            save_session(self.session_id, self.messages)
                            break
                    else:
                        self.messages.append({"role": "user", "content": prompt})
                        await self._run_agent(prompt)
                else:
                    self.messages.append({"role": "user", "content": prompt})
                    await self._run_agent(prompt)
        except KeyboardInterrupt:
            print_info("\nGoodbye!")
        finally:
            elapsed = time.time() - self.start_time if self.start_time else 0
            save_session(self.session_id, self.messages)
            usage_stats.track_session()
            if self.agent:
                await self.agent.cleanup()

    async def _run_agent(self, prompt: str):
        self.messages.append({"role": "user", "content": prompt})

        status = Live(Spinner("dots", text="", style="dim"), console=console, refresh_per_second=10)
        status.start()

        try:
            result = await asyncio.wait_for(self.agent.run(prompt), timeout=300)
            status.stop()
            text = str(result) if result else ""
            self.messages.append({"role": "assistant", "content": text})
            save_session(self.session_id, self.messages)
            if text:
                print(text)
        except asyncio.TimeoutError:
            status.stop()
            print_error("Request timed out (300s). Check config.")
        except asyncio.CancelledError:
            status.stop()
        except Exception as e:
            status.stop()
            err = str(e)
            if "401" in err or "Unauthorized" in err:
                msg = "Invalid API key. Run: openmanus"
            elif "404" in err or "not found" in err.lower() or "model" in err.lower():
                msg = "Model not found. Check config/config.toml"
            elif "timeout" in err.lower() or "timed out" in err.lower():
                msg = "Request timed out. Check endpoint."
            else:
                msg = f"Error: {err[:200]}"
            print_error(msg)


def create_session_obj(auto_approve=False, mini=False, no_replay=False,
                       agent_name=None, model=None, pure=False) -> InteractiveSession:
    return InteractiveSession(
        auto_approve=auto_approve, mini=mini, no_replay=no_replay,
        agent_name=agent_name, model=model, pure=pure,
    )
