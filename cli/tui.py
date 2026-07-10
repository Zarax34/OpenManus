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
            print_info("Testing LLM connection...")
            try:
                from app.schema import Message
                test = await asyncio.wait_for(
                    self.agent.llm.ask(
                        messages=[Message.user_message("respond with just 'ok'")],
                        stream=False,
                    ),
                    timeout=15,
                )
                print_done("LLM connected")
            except asyncio.TimeoutError:
                print_warning("LLM connection timed out. Check the model name and API endpoint in config.")
            except Exception as e:
                err = str(e)
                if "401" in err:
                    print_error("Invalid API key. Run setup again: openmanus")
                elif "404" in err or "not found" in err.lower():
                    print_error(f"Model not found. Check model name in config/config.toml")
                else:
                    print_warning(f"LLM issue: {err[:100]}")

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
            if self.agent:
                await self.agent.cleanup()

    async def _run_agent(self, prompt: str):
        self.messages.append({"role": "user", "content": prompt})

        if not self.mini:
            console.print(Rule(style="dim"))

        try:
            result = await asyncio.wait_for(self.agent.run(prompt), timeout=300)
            self.messages.append({"role": "assistant", "content": str(result) if result else ""})
            save_session(self.session_id, self.messages)
        except asyncio.TimeoutError:
            msg = "Request timed out (300s). Check your API key and model name in config."
            print_error(msg)
            self.messages.append({"role": "assistant", "content": msg})
        except asyncio.CancelledError:
            print_warning("Task cancelled")
        except Exception as e:
            err = str(e)
            if "401" in err or "Unauthorized" in err:
                msg = "API key is invalid. Run setup again: openmanus"
            elif "404" in err or "not found" in err.lower() or "model" in err.lower():
                msg = f"Model not found. Check the model name in config/config.toml"
            elif "timeout" in err.lower() or "timed out" in err.lower():
                msg = "Request timed out. Check your API endpoint."
            else:
                msg = f"Error: {err[:200]}"
            print_error(msg)
            self.messages.append({"role": "assistant", "content": msg})


class MiniSession(InteractiveSession):
    async def start(self):
        print_banner(mini=True)
        print_info(f"Session: {self.session_id[:8]}")

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
            if self.agent:
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
