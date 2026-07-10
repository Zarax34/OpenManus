import asyncio
import os
import sys
import time
from typing import Optional

from cli.session import create_session, save_session, list_sessions, get_session
from cli.stats import usage_stats

from prompt_toolkit import Application
from prompt_toolkit.layout import Layout, HSplit, Window, FormattedTextControl
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.application import get_app
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.styles import Style

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


TUI_STYLE = Style.from_dict({
    "header": "bold bg:#1a1a2e #e0e0e0",
    "header.model": "#7ec8e3",
    "header.session": "bold #a8d8ea",
    "status": "bg:#1a1a2e #888888 italic",
    "status.thinking": "bg:#1a1a2e #f0c040 bold",
    "input": "bg:#16213e #e0e0e0",
    "input.prompt": "bold #00d4aa",
    "user.msg": "bold #7ec8e3",
    "assistant.msg": "#e0e0e0",
    "error.msg": "#ff6b6b",
    "info.msg": "#a8d8ea",
    "divider": "#333333",
})


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

        self._thinking = False
        self._conversation: list[tuple[str, str]] = []
        self._app: Optional[Application] = None
        self._conv_scroll = 0

        header_text = self._build_header()
        self._header_control = FormattedTextControl(header_text)
        self._header_window = Window(content=self._header_control, height=1, style="bg:#1a1a2e")

        self._conv_control = FormattedTextControl(self._get_conversation)
        self._conv_window = Window(
            content=self._conv_control,
            wrap_lines=True,
            style="bg:#0f3460",
        )

        self._status_control = FormattedTextControl(self._get_status)
        self._status_window = Window(content=self._status_control, height=1, style="bg:#1a1a2e")

        self._input_field = TextArea(
            height=1,
            prompt="> ",
            multiline=False,
            accept_handler=self._on_accept,
            completer=_SlashCompleter(SLASH_COMMANDS),
            complete_while_typing=True,
            style="bg:#16213e #e0e0e0",
        )

        body = HSplit([
            self._header_window,
            Window(height=1, char=" ", style="bg:#0f3460"),
            self._conv_window,
            self._input_field,
            self._status_window,
        ])
        self._layout = Layout(body, focused_element=self._input_field)

        kb = KeyBindings()

        @kb.add("c-c")
        def _exit(event):
            event.app.exit()

        @kb.add("c-l")
        def _clear(event):
            self._conversation.clear()
            event.app.invalidate()

        self._kb = kb

    def _build_header(self):
        model = _format_model(self._model) if self._model else "?"
        sid = self.session_id[:8] if self.session_id else "?"
        return [
            ("class:header", " openmanus "),
            ("class:header.model", f" {model} "),
            ("class:header.session", f" {sid} "),
            ("class:header", f" {self.agent_name} "),
        ]

    def _get_conversation(self):
        return self._conversation

    def _get_status(self):
        if self._thinking:
            return [("class:status.thinking", " \u25cf Processing...")]
        return [("class:status", " /help  /new  /exit  \u00b7 Ctrl+C to quit")]

    def _add_msg(self, style: str, text: str):
        self._conversation.append((style, text))
        try:
            get_app().invalidate()
        except Exception:
            pass

    def _invalidate(self):
        try:
            get_app().invalidate()
        except Exception:
            pass

    async def _on_accept(self, buf: Buffer) -> bool:
        text = buf.text.strip()
        buf.text = ""
        if not text:
            return True

        self._add_msg("class:user.msg", f"> {text}")

        if text.lower() in ("exit", "quit", "q"):
            get_app().exit()
            return True

        if text.startswith("/"):
            parts = text.split(None, 1)
            cmd = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""
            await self._handle_slash(cmd, args)
            return True

        if not self.agent:
            self._add_msg("class:error.msg", "  Agent not initialized. Check config.")
            return True

        if "@" in text:
            from app.tool.task import SUB_AGENTS
            for name in SUB_AGENTS:
                mention = f"@{name}"
                if mention in text:
                    task_prompt = text.replace(mention, "").strip()
                    self._add_msg("class:info.msg", f"  Invoking @{name}...")
                    try:
                        from app.tool.task import Task
                        t = Task()
                        res = await t.execute(prompt=task_prompt or "Handle this task", agent=name)
                        self._add_msg("class:assistant.msg", f"  @{name}: {res}")
                        self.messages.append({"role": "user", "content": text})
                        self.messages.append({"role": "assistant", "content": f"[@{name}]: {res}"})
                        save_session(self.session_id, self.messages)
                    except Exception as e:
                        self._add_msg("class:error.msg", f"  @{name} failed: {e}")
                    return True

        self._input_field.read_only = True
        self._thinking = True
        self._invalidate()
        try:
            await self._run_agent(text)
        finally:
            self._thinking = False
            self._input_field.read_only = False
            self._invalidate()
        return True

    async def _run_agent(self, text: str):
        try:
            result = await asyncio.wait_for(self.agent.run(text), timeout=300)
            out = str(result) if result else ""
            if out:
                self._add_msg("class:assistant.msg", out)
            self._sync_messages()
            save_session(self.session_id, self.messages)
        except asyncio.TimeoutError:
            self._add_msg("class:error.msg", "  Request timed out (300s). Check config.")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            err = str(e)
            if "401" in err or "Unauthorized" in err:
                msg = "Invalid API key. Run: openmanus"
            elif "404" in err or "not found" in err.lower() or "model" in err.lower():
                msg = "Model not found. Check config/config.toml"
            elif "timeout" in err.lower() or "timed out" in err.lower():
                msg = "Request timed out. Check endpoint."
            else:
                msg = f"Error: {err[:200]}"
            self._add_msg("class:error.msg", f"  {msg}")

    async def _handle_slash(self, cmd: str, args: str):
        match cmd:
            case "/help":
                self._add_msg("class:info.msg", "  Slash Commands:")
                for name, desc in SLASH_COMMANDS.items():
                    self._add_msg("", f"    {name:<20} {desc}")

            case "/new":
                self.messages = []
                self.session_id = create_session()
                save_session(self.session_id, self.messages)
                self._add_msg("class:info.msg", "  New session started")

            case "/exit":
                get_app().exit()

            case "/clear":
                self._conversation.clear()
                self._invalidate()

            case "/models":
                from app.config import config
                self._add_msg("", "  Models:")
                for name, settings in config.llm.items():
                    model = settings.model or "?"
                    url = settings.base_url or ""
                    self._add_msg("", f"    {name:<12} {model:<30} {url}")

            case "/sessions":
                sessions = list_sessions()
                if not sessions:
                    self._add_msg("class:info.msg", "  No sessions found.")
                else:
                    self._add_msg("", f"  {'Session ID':<24} {'Title':<50} {'Updated'}")
                    self._add_msg("", "  " + "\u2500" * 96)
                    for s in sessions:
                        sid = s["id"][:8]
                        raw = s.get("preview", "")
                        title = raw[:48].replace("\n", " ") if raw else "New session"
                        updated = s.get("created_at", "").replace("T", " ")[:19]
                        self._add_msg("", f"  {sid:<24} {title:<50} {updated}")

            case "/pick":
                all_sessions = list_sessions()
                if not all_sessions:
                    self._add_msg("class:info.msg", "  No sessions found")
                    return
                self._add_msg("", "")
                for i, s in enumerate(all_sessions[:20], 1):
                    sid = s["id"][:8]
                    preview = (s.get("preview", "") or "New session")[:50].replace("\n", " ")
                    msg_count = s.get("message_count", 0)
                    self._add_msg("", f"  [{i}] {sid:<12} {msg_count:>3} msgs  {preview}")
                self._add_msg("", "")
                self._add_msg("class:info.msg", f"  Type /pick <number> to select a session")
                if args and args.isdigit():
                    idx = int(args) - 1
                    if 0 <= idx < len(all_sessions):
                        self._load_session(all_sessions[idx]["id"])

            case "/export":
                from cli.export_import import export_session
                path = export_session(self.session_id)
                if path:
                    self._add_msg("class:info.msg", f"  Exported session {self.session_id[:8]} to {path}")
                else:
                    self._add_msg("class:error.msg", "  Session export failed")

            case "/compact":
                msgs = self.agent.memory.messages if self.agent else []
                if len(msgs) < 4:
                    self._add_msg("class:info.msg", "  Conversation too short to compact")
                    return
                try:
                    from app.schema import Message
                    text = "\n".join(
                        (m.content or "") if hasattr(m, 'content') else (m.get("content", "") or "")
                        for m in msgs
                        if (getattr(m, 'role', None) or m.get("role")) in ("user", "assistant")
                    )
                    summary = await self.agent.llm.ask(
                        messages=[Message.user_message(
                            f"Summarize this conversation concisely:\n\n{text[-4000:]}"
                        )],
                        stream=False,
                    )
                    self.agent.memory.clear()
                    self.agent.update_memory("user", f"Previous conversation summary:\n{summary}")
                    self._sync_messages()
                    self._add_msg("class:info.msg", "  Conversation compacted")
                except Exception as e:
                    self._add_msg("class:error.msg", f"  Compact failed: {e}")

            case "/agent":
                self._add_msg("class:info.msg", f"  Agent: {self.agent_name}")
                self._add_msg("class:info.msg", f"  Model: {_format_model(self._model) if self._model else '?'}")
                self._add_msg("class:info.msg", f"  Session: {self.session_id[:8]}")
                self._add_msg("class:info.msg", f"  Messages: {len(self.messages)}")
                self._add_msg("", "  Sub-agents (use @name to invoke):")
                from app.tool.task import SUB_AGENTS
                for name, info in SUB_AGENTS.items():
                    self._add_msg("", f"    @{name:<12} {info['description']}")

            case "/agents":
                from app.tool.task import SUB_AGENTS
                self._add_msg("", "  Sub-agents:")
                for name, info in SUB_AGENTS.items():
                    self._add_msg("", f"    @{name:<12} {info['description']}")
                self._add_msg("class:info.msg", "  Use @name in your prompt to invoke a sub-agent")

            case "/connect":
                parts = args.split(None, 3) if args else []
                try:
                    from cli.providers import add_provider as _add, KNOWN_PROVIDERS
                    if not parts:
                        self._add_msg("", "  Usage: /connect <name> [model] [base_url] [api_key]")
                        self._add_msg("", "  Known providers: " + ", ".join(KNOWN_PROVIDERS.keys()))
                        return
                    name = parts[0]
                    if len(parts) >= 4:
                        _add(name, parts[1], parts[2], parts[3], set_default=True)
                    elif len(parts) >= 2:
                        _add(name, parts[1], "", "", set_default=True)
                    elif name.lower() in KNOWN_PROVIDERS:
                        info = KNOWN_PROVIDERS[name.lower()]
                        _add(name, info["models"][0] if info["models"] else "", info["base_url"], "", set_default=True)
                    else:
                        self._add_msg("", "  Usage: /connect <name> <model> <base_url> <api_key>")
                        self._add_msg("class:info.msg", "  Or use: openmanus connect (outside TUI) for interactive setup")
                        return
                    self._add_msg("class:info.msg", f"  Provider '{name}' added")
                except Exception as e:
                    self._add_msg("class:error.msg", f"  Connect failed: {e}")

            case "/stats":
                stats = usage_stats.get_summary()
                for k, v in stats.items():
                    self._add_msg("", f"  {k:<22} {v}")

            case "/skill":
                from app.tool.skill import _discover_skills
                skills = _discover_skills()
                if args:
                    for s in skills:
                        if s["name"] == args:
                            self._add_msg("", f"  --- {s['name']} ---")
                            self._add_msg("", f"  {s['description']}")
                            self._add_msg("", f"  Path: {s['path']}")
                            return
                    self._add_msg("class:error.msg", f"  Skill '{args}' not found")
                    return
                if not skills:
                    self._add_msg("class:info.msg", "  No skills found")
                    return
                for s in skills:
                    self._add_msg("", f"  {s['name']:<20} {s['description']}")
                self._add_msg("class:info.msg", "  Use '/skill <name>' to view details")

            case _:
                self._add_msg("class:error.msg", f"  Unknown command: {cmd}")

    def _load_session(self, sid: str):
        data = get_session(sid)
        if not data:
            self._add_msg("class:error.msg", f"  Session '{sid[:8]}' not found")
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
        self._add_msg("class:info.msg", f"  Switched to session {sid[:8]} ({len(self.messages)} messages)")

    async def start(self):
        try:
            from app.agent.manus import Manus
            self.agent = await Manus.create()
        except ImportError as e:
            missing = str(e).replace("No module named ", "")
            print(f"Error: Missing dependency: {missing}", file=sys.stderr)
            return
        except Exception as e:
            print(f"Error: Failed to initialize agent: {e}", file=sys.stderr)
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
                    self._add_msg("class:user.msg", f"> {content}")
                elif role == "assistant":
                    self._add_msg("class:assistant.msg", content)

        self.start_time = time.time()

        app = Application(
            layout=self._layout,
            key_bindings=self._kb,
            full_screen=True,
            mouse_support=True,
            style=TUI_STYLE,
        )
        self._app = app
        await app.run_async()

        elapsed = time.time() - self.start_time if self.start_time else 0
        save_session(self.session_id, self.messages)
        usage_stats.track_session()
        if self.agent:
            await self.agent.cleanup()

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
