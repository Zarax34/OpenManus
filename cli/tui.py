import asyncio
import sys
import time
import json
from datetime import datetime
from typing import Optional

from cli.session import create_session, save_session
from cli.stats import usage_stats
from cli.ui import (
    RICH_AVAILABLE, console, print_banner, print_thinking,
    print_tool_call, print_tool_result, print_info, print_warning,
    print_error, print_done, input_with_prompt, confirm_action,
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


class InteractiveSession:
    def __init__(self, auto_approve: bool = False, mini: bool = False, no_replay: bool = False,
                 agent_name: str = None, model: str = None, pure: bool = False):
        self.auto_approve = auto_approve
        self.mini = mini
        self.no_replay = no_replay
        self.agent_name = agent_name
        self.model = model
        self.pure = pure
        self.session_id = create_session()
        self.messages = []
        self.agent = None
        self.start_time = None

    async def start(self):
        from app.agent.manus import Manus

        if not self.mini:
            print_banner()

        mode_str = "pure" if self.pure else "interactive"
        mini_str = " [dim]mini[/]" if self.mini else ""
        auto_str = " [yellow]auto-approve[/]" if self.auto_approve else ""
        print_info(f"OpenManus {mode_str} mode{mini_str}{auto_str}")
        print_info(f"Session: [cyan]{self.session_id[:8]}[/]")
        if self.agent_name:
            print_info(f"Agent: [cyan]{self.agent_name}[/]")
        if self.model:
            print_info(f"Model: [cyan]{self.model}[/]")
        print_info("[dim]Type 'exit' or Ctrl+C to quit[/]\n")

        self.agent = await Manus.create()

        if not self.no_replay and not self.mini:
            console.print("[dim]New session started[/]")

        self.start_time = time.time()

        try:
            while True:
                prompt = input_with_prompt()
                if prompt.lower() in ("exit", "quit", "q"):
                    break
                if not prompt.strip():
                    continue

                self.messages.append({"role": "user", "content": prompt})
                await self._run_agent(prompt)
        except KeyboardInterrupt:
            print_info("\n\nGoodbye!")
        finally:
            elapsed = time.time() - self.start_time if self.start_time else 0
            save_session(self.session_id, self.messages)
            usage_stats.track_session()
            print_done(f"Session saved [dim]({elapsed:.1f}s)[/]")
            await self.agent.cleanup()

    async def _run_agent(self, prompt: str):
        self.messages.append({"role": "user", "content": prompt})

        if not self.mini:
            console.print(Rule(style="dim"))

        try:
            result = await self.agent.run(prompt)
            self.messages.append({"role": "assistant", "content": str(result) if result else ""})
            save_session(self.session_id, self.messages)
        except asyncio.CancelledError:
            print_warning("Task cancelled")
        except Exception as e:
            print_error(f"Error: {e}")
            self.messages.append({"role": "assistant", "content": f"Error: {e}"})


class MiniSession(InteractiveSession):
    async def start(self):
        from app.agent.manus import Manus

        print_banner(mini=True)
        print_info(f"Session: {self.session_id[:8]}")

        self.agent = await Manus.create()
        self.start_time = time.time()

        try:
            while True:
                prompt = input_with_prompt(">", allow_empty=False)
                if prompt.lower() in ("exit", "quit", "q"):
                    break
                if not prompt.strip():
                    continue

                self.messages.append({"role": "user", "content": prompt})
                print(f"  Processing...")

                try:
                    result = await self.agent.run(prompt)
                    self.messages.append({"role": "assistant", "content": str(result) if result else ""})
                except Exception as e:
                    print(f"  Error: {e}")
        except KeyboardInterrupt:
            pass
        finally:
            save_session(self.session_id, self.messages)
            usage_stats.track_session()
            await self.agent.cleanup()


def create_session_obj(auto_approve=False, mini=False, no_replay=False,
                       agent_name=None, model=None, pure=False) -> InteractiveSession:
    if mini:
        return MiniSession(
            auto_approve=auto_approve, mini=True, no_replay=no_replay,
            agent_name=agent_name, model=model, pure=pure,
        )
    return InteractiveSession(
        auto_approve=auto_approve, mini=mini, no_replay=no_replay,
        agent_name=agent_name, model=model, pure=pure,
    )
