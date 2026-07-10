import asyncio
import os
import shutil
import subprocess
import sys
import time
import json
from datetime import datetime
from typing import Optional

from cli.session import create_session, save_session, list_sessions, delete_session, get_session
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
    "/pick": "Interactive session picker",
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


def _load_session(session: "InteractiveSession", sid: str):
    """Switch the active session to an existing one."""
    data = get_session(sid)
    if not data:
        print_error(f"Session '{sid[:8]}' not found")
        return
    session.session_id = data["id"]
    session.messages = data.get("messages", [])
    if session.agent:
        session.agent.memory.clear()
        from app.schema import Message as Msg
        for m in session.messages:
            role = m.get("role", "user")
            content = m.get("content", "") or ""
            if role == "user":
                session.agent.update_memory("user", content)
            elif role == "assistant":
                session.agent.update_memory("assistant", content)
            elif role == "tool":
                session.agent.update_memory("tool", content,
                    tool_call_id=m.get("tool_call_id", ""),
                    name=m.get("name", ""))
    print_info(f"Switched to session {sid[:8]} ({len(session.messages)} messages)")


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

        case "/pick":
            all_sessions = list_sessions()
            if not all_sessions:
                print_info("No sessions found")
                return True
            print()
            for i, s in enumerate(all_sessions[:20], 1):
                sid = s["id"][:8]
                preview = (s.get("preview", "") or "New session")[:50].replace("\n", " ")
                msg_count = s.get("message_count", 0)
                print(f"  [{i}] {sid:<12} {msg_count:>3} msgs  {preview}")
            print()
            choice = input(f"  Pick session [1-{min(len(all_sessions), 20)}] or Enter to cancel: ").strip()
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(all_sessions):
                    sid = all_sessions[idx]["id"]
                    _load_session(session, sid)
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
            msgs = session.agent.memory.messages if session.agent else []
            if len(msgs) < 4:
                print_info("Conversation too short to compact")
                return True
            try:
                from app.schema import Message
                text = "\n".join(
                    (m.content or "") if hasattr(m, 'content') else (m.get("content", "") or "")
                    for m in msgs
                    if (getattr(m, 'role', None) or m.get("role")) in ("user", "assistant")
                )
                summary = await session.agent.llm.ask(
                    messages=[Message.user_message(
                        f"Summarize this conversation concisely, keeping key details:\n\n{text[-4000:]}"
                    )],
                    stream=False,
                )
                session.agent.memory.clear()
                session.agent.update_memory("user", f"Previous conversation summary:\n{summary}")
                session._sync_messages()
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
                 agent_name: str = None, model: str = None, pure: bool = False,
                 session_id: str = None, fork: bool = False):
        self.auto_approve = auto_approve
        self.mini = mini
        self.no_replay = no_replay
        self.agent_name = agent_name or "Manus"
        self._model = model
        self.pure = pure
        self.fork = fork
        self.messages = []
        self.agent = None
        self.start_time = None

        if session_id:
            data = get_session(session_id)
            if data:
                self.session_id = data["id"]
                self.messages = data.get("messages", [])
                print_info(f"Resumed session {self.session_id[:8]}")
            else:
                print_error(f"Session '{session_id}' not found, starting new")
                self.session_id = create_session()
        else:
            self.session_id = create_session()

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

        if self.messages:
            from app.schema import Message as Msg
            for m in self.messages:
                role = m.get("role", "user")
                content = m.get("content", "") or ""
                if role == "user":
                    self.agent.update_memory("user", content)
                elif role == "assistant":
                    self.agent.update_memory("assistant", content)
                elif role == "tool":
                    self.agent.update_memory("tool", content, tool_call_id=m.get("tool_call_id", ""), name=m.get("name", ""))
            self._sync_messages()

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
                        await self._run_agent(prompt)
                else:
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
        status = Live(Spinner("dots", text="", style="dim"), console=console, refresh_per_second=10)
        status.start()

        try:
            result = await asyncio.wait_for(self.agent.run(prompt), timeout=300)
            status.stop()
            text = str(result) if result else ""
            self._sync_messages()
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

    def _sync_messages(self):
        """Sync TUI log from agent memory"""
        if not self.agent:
            return
        self.messages = [m.to_dict() if hasattr(m, 'to_dict') else m for m in self.agent.memory.messages]
        save_session(self.session_id, self.messages)


def create_session_obj(auto_approve=False, mini=False, no_replay=False,
                       agent_name=None, model=None, pure=False,
                       session_id=None, fork=False) -> InteractiveSession:
    return InteractiveSession(
        auto_approve=auto_approve, mini=mini, no_replay=no_replay,
        agent_name=agent_name, model=model, pure=pure,
        session_id=session_id, fork=fork,
    )
