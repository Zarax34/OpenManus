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


def _format_model(model: str) -> str:
    if model and "/" in model:
        parts = model.split("/", 1)
        return parts[1] if parts[0] in ("z-ai",) else model
    return model or "unknown"


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

    def _agent_line(self) -> str:
        return f"> {self.agent_name} \u00b7 {_format_model(self._model)}"

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
