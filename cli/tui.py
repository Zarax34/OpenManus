import asyncio
import sys
import time
from typing import Optional

from cli.session import create_session, save_session, list_sessions, get_session
from cli.stats import usage_stats
from cli.ui import (
    RICH_AVAILABLE, console, print_banner, print_info, print_error, print_done,
    print_sessions_table, print_stats_table,
)

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import InMemoryHistory


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
    "/skill": "List or load a skill",
    "/agents": "List available sub-agents",
}


def _format_model(model: str) -> str:
    if model and "/" in model:
        parts = model.split("/", 1)
        return parts[1] if parts[0] in ("z-ai",) else model
    return model or "?"


class _SlashCompleter(Completer):
    def __init__(self, commands: dict):
        self.commands = commands

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith("/"):
            word = text
            for cmd in self.commands:
                if cmd.startswith(word):
                    yield Completion(cmd, start_position=-len(text))


_CS = "\033[?1049h"
_CE = "\033[?1049l"
_CLS = "\033[2J\033[H"
_CLR = "\033[J"


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
            else:
                self.session_id = create_session()
        else:
            self.session_id = create_session()

        self._input = PromptSession(
            completer=_SlashCompleter(SLASH_COMMANDS),
            complete_while_typing=True,
            history=InMemoryHistory(),
        )

    async def start(self):
        sys.stdout.write(_CS + _CLS)
        sys.stdout.flush()

        self._draw_header()

        try:
            from app.agent.manus import Manus
            self.agent = await Manus.create()
        except ImportError as e:
            missing = str(e).replace("No module named ", "")
            print_error(f"Missing dependency: {missing}")
            print_info("Install: pip install -r requirements.txt")
            await self._pause()
            return
        except Exception as e:
            print_error(f"Failed to initialize agent: {e}")
            await self._pause()
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
                    self.agent.update_memory("tool", content,
                        tool_call_id=m.get("tool_call_id", ""),
                        name=m.get("name", ""))
            self._sync_messages()
            for m in self.messages:
                role = m.get("role", "")
                content = m.get("content", "")[:500] or ""
                if role == "user":
                    print(f"  > {content}")
                elif role == "assistant":
                    print(f"  {content}")

        self.start_time = time.time()

        while True:
            try:
                text = await self._input.prompt_async("> ")
            except (EOFError, KeyboardInterrupt):
                break

            text = text.strip()
            if not text:
                continue

            if text.lower() in ("exit", "quit", "q"):
                break

            if text.startswith("/"):
                handled = await self._handle_slash(text)
                if not handled:
                    break
                continue

            print(f"  > {text}")

            if "@" in text:
                from app.tool.task import SUB_AGENTS
                matched = False
                for name in SUB_AGENTS:
                    mention = f"@{name}"
                    if mention in text:
                        task_prompt = text.replace(mention, "").strip()
                        print_info(f"Invoking @{name}...")
                        try:
                            from app.tool.task import Task
                            t = Task()
                            res = await t.execute(prompt=task_prompt or "Handle this task", agent=name)
                            print(f"  @{name}: {res}")
                            self.messages.append({"role": "user", "content": text})
                            self.messages.append({"role": "assistant", "content": f"[@{name}]: {res}"})
                            save_session(self.session_id, self.messages)
                        except Exception as e:
                            print_error(f"@{name} failed: {e}")
                        matched = True
                        break
                if matched:
                    continue

            if not self.agent:
                print_error("Agent not initialized")
                continue

            print("  \033[33m\u25cf Processing...\033[0m")
            try:
                result = await asyncio.wait_for(self.agent.run(text), timeout=300)
                out = str(result) if result else ""
                if out:
                    print(f"  {out}")
                self._sync_messages()
                save_session(self.session_id, self.messages)
            except asyncio.TimeoutError:
                print_error("Request timed out (300s)")
            except Exception as e:
                err = str(e)
                if "401" in err or "Unauthorized" in err:
                    print_error("Invalid API key")
                elif "404" in err or "not found" in err.lower() or "model" in err.lower():
                    print_error("Model not found in config/config.toml")
                elif "timeout" in err.lower() or "timed out" in err.lower():
                    print_error("Request timed out")
                else:
                    print_error(str(err)[:200])

        elapsed = time.time() - self.start_time if self.start_time else 0
        save_session(self.session_id, self.messages)
        usage_stats.track_session()
        if self.agent:
            await self.agent.cleanup()

        sys.stdout.write(_CE)
        sys.stdout.flush()

    def _draw_header(self):
        model = _format_model(self._model) if self._model else "?"
        sid = self.session_id[:8] if self.session_id else "?"
        print(f"  openmanus  {model}  {sid}  {self.agent_name}")
        print(f"  \u2500" * 56)
        print()

    async def _pause(self):
        print()
        try:
            await self._input.prompt_async("Press Enter to continue...")
        except (EOFError, KeyboardInterrupt):
            pass

    async def _handle_slash(self, line: str) -> bool:
        parts = line.split(None, 1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        match cmd:
            case "/help":
                print("  Slash Commands:")
                for name, desc in SLASH_COMMANDS.items():
                    print(f"    {name:<20} {desc}")

            case "/new":
                self.messages = []
                self.session_id = create_session()
                save_session(self.session_id, self.messages)
                print_info("New session started")

            case "/clear":
                sys.stdout.write(_CLS)
                self._draw_header()

            case "/models":
                from app.config import config
                print("  Models:")
                for name, settings in config.llm.items():
                    model = settings.model or "?"
                    url = settings.base_url or ""
                    print(f"    {name:<12} {model:<30} {url}")

            case "/sessions":
                sessions = list_sessions()
                if not sessions:
                    print_info("No sessions found.")
                else:
                    print_sessions_table(sessions)

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
                if args and args.isdigit():
                    idx = int(args) - 1
                    if 0 <= idx < len(all_sessions):
                        self._load_session(all_sessions[idx]["id"])
                else:
                    try:
                        choice = await self._input.prompt_async("  Pick session [1-{}] or Enter: ".format(min(len(all_sessions), 20)))
                        if choice.isdigit():
                            idx = int(choice) - 1
                            if 0 <= idx < len(all_sessions):
                                self._load_session(all_sessions[idx]["id"])
                    except (EOFError, KeyboardInterrupt):
                        pass

            case "/export":
                from cli.export_import import export_session
                path = export_session(self.session_id)
                if path:
                    print_info(f"Exported session {self.session_id[:8]} to {path}")
                else:
                    print_error("Export failed")

            case "/compact":
                msgs = self.agent.memory.messages if self.agent else []
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
                    summary = await self.agent.llm.ask(
                        messages=[Message.user_message(f"Summarize this conversation concisely:\n\n{text[-4000:]}")],
                        stream=False,
                    )
                    self.agent.memory.clear()
                    self.agent.update_memory("user", f"Previous conversation summary:\n{summary}")
                    self._sync_messages()
                    print_info("Conversation compacted")
                except Exception as e:
                    print_error(f"Compact failed: {e}")

            case "/agent":
                print_info(f"Agent: {self.agent_name}")
                print_info(f"Model: {_format_model(self._model) if self._model else '?'}")
                print_info(f"Session: {self.session_id[:8]}")
                print_info(f"Messages: {len(self.messages)}")
                print("  Sub-agents (use @name):")
                from app.tool.task import SUB_AGENTS
                for name, info in SUB_AGENTS.items():
                    print(f"    @{name:<12} {info['description']}")

            case "/agents":
                from app.tool.task import SUB_AGENTS
                print("  Sub-agents:")
                for name, info in SUB_AGENTS.items():
                    print(f"    @{name:<12} {info['description']}")
                print_info("Use @name in your prompt")

            case "/connect":
                conn_args = args.split(None, 3) if args else []
                try:
                    from cli.providers import add_provider as _add, KNOWN_PROVIDERS
                    if not conn_args:
                        print("  Usage: /connect <name> [model] [base_url] [api_key]")
                        print("  Known: " + ", ".join(KNOWN_PROVIDERS.keys()))
                        return True
                    name = conn_args[0]
                    if len(conn_args) >= 4:
                        _add(name, conn_args[1], conn_args[2], conn_args[3], set_default=True)
                    elif len(conn_args) >= 2:
                        _add(name, conn_args[1], "", "", set_default=True)
                    elif name.lower() in KNOWN_PROVIDERS:
                        info = KNOWN_PROVIDERS[name.lower()]
                        _add(name, info["models"][0] if info["models"] else "", info["base_url"], "", set_default=True)
                    else:
                        print("  Usage: /connect <name> <model> <base_url> <api_key>")
                        return True
                    print_info(f"Provider '{name}' added")
                except Exception as e:
                    print_error(f"Connect failed: {e}")

            case "/stats":
                stats = usage_stats.get_summary()
                print_stats_table(stats)

            case "/skill":
                from app.tool.skill import _discover_skills
                skills = _discover_skills()
                if args:
                    for s in skills:
                        if s["name"] == args:
                            print(f"  --- {s['name']} ---")
                            print(f"  {s['description']}")
                            print(f"  Path: {s['path']}")
                            return True
                    print_error(f"Skill '{args}' not found")
                    return True
                if not skills:
                    print_info("No skills found")
                    return True
                for s in skills:
                    print(f"  {s['name']:<20} {s['description']}")
                print_info("Use '/skill <name>' to view details")

            case _:
                print_error(f"Unknown: {cmd}")

        return True

    def _load_session(self, sid: str):
        data = get_session(sid)
        if not data:
            print_error(f"Session '{sid[:8]}' not found")
            return
        self.session_id = data["id"]
        self.messages = data.get("messages", [])
        if self.agent:
            self.agent.memory.clear()
            from app.schema import Message as Msg
            for m in self.messages:
                role = m.get("role", "user")
                content = m.get("content", "") or ""
                if role == "user":
                    self.agent.update_memory("user", content)
                elif role == "assistant":
                    self.agent.update_memory("assistant", content)
                elif role == "tool":
                    self.agent.update_memory("tool", content,
                        tool_call_id=m.get("tool_call_id", ""),
                        name=m.get("name", ""))
        print_info(f"Switched to session {sid[:8]} ({len(self.messages)} messages)")

    def _sync_messages(self):
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
