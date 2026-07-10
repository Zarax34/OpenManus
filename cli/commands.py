import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from cli.session import (
    create_session,
    save_session,
    list_sessions,
    get_session,
    delete_session,
)
from cli.stats import usage_stats
from cli.ui import (
    console,
    print_banner,
    print_info,
    print_warning,
    print_error,
    print_done,
    print_config_table,
    print_sessions_table,
    print_models_table,
    print_providers_table,
    print_stats_table,
    print_agents_table,
    print_debug_info,
    print_export_result,
    input_with_prompt,
    confirm_action,
    format_json,
)
from cli.tui import create_session_obj
from cli.providers import (
    list_providers as _list_providers,
    add_provider as _add_provider,
    remove_provider as _remove_provider,
    set_default_provider as _set_default_provider,
    get_provider,
    get_default_provider,
    KNOWN_PROVIDERS,
    add_opencode_provider,
)
from cli.plugins import (
    list_plugins as _list_plugins,
    install_plugin as _install_plugin,
    remove_plugin as _remove_plugin,
    load_plugins,
)
from cli.debug import collect_debug_info, get_system_info, get_env_info, get_config_info, check_dependencies
from cli.completion import (
    generate_bash_completion,
    generate_zsh_completion,
    generate_fish_completion,
    install_completion,
)


async def run_interactive(args):
    """Interactive REPL mode (default)"""
    session = create_session_obj(
        auto_approve=args.auto,
        mini=args.mini,
        no_replay=args.no_replay,
        agent_name=args.agent,
        model=args.model,
        pure=args.pure,
    )
    await session.start()


async def run_single(args):
    """Run agent with a single prompt"""
    if args.prompt:
        prompt = args.prompt
    else:
        prompt = input_with_prompt()
        if not prompt or not prompt.strip():
            print_error("No prompt provided.")
            return

    session_id = create_session()
    messages = [{"role": "user", "content": prompt}]

    try:
        from app.agent.manus import Manus
        agent = await Manus.create()
    except ImportError as e:
        missing = str(e).replace("No module named ", "")
        print_error(f"Missing dependency: {missing}")
        print_info("Install required packages: pip install -r requirements.txt")
        return
    except Exception as e:
        print_error(f"Failed to initialize agent: {e}")
        return

    try:
        print_info("Processing your request...")
        result = await agent.run(prompt)
        if result:
            messages.append({"role": "assistant", "content": str(result)})
        print_done("Done")
        save_session(session_id, messages)
        usage_stats.track_session()
    except KeyboardInterrupt:
        print_info("\nInterrupted.")
    finally:
        await agent.cleanup()


def cmd_session(args):
    """Manage sessions"""
    if args.action == "list":
        sessions = list_sessions()
        if not sessions:
            print_info("No sessions found.")
            return
        print_sessions_table(sessions)
        print_info(f"\nTotal: {len(sessions)} session(s)")

    elif args.action == "show":
        if not args.session_id:
            print_error("Session ID required.")
            return
        data = get_session(args.session_id)
        if not data:
            print_error(f"Session '{args.session_id}' not found.")
            return
        messages = data.get("messages", [])
        print_info(f"\nSession: {data['id']}")
        print_info(f"Created: {data.get('created_at', 'unknown')}")
        print_info(f"Messages: {len(messages)}")
        for msg in messages:
            role = msg.get("role", "?")
            content = (msg.get("content") or "")[:200]
            if role == "user":
                console.print(f"\n  [bold cyan]User:[/] {content}")
            elif role == "assistant":
                console.print(f"\n  [bold green]Agent:[/] {content[:300]}")
            elif role == "tool":
                name = msg.get("name", "tool")
                console.print(f"\n  [magenta]{name}:[/] {content[:200]}")

    elif args.action == "delete":
        if not args.session_id:
            print_error("Session ID required.")
            return
        if not confirm_action(f"Delete session '{args.session_id[:8]}'?"):
            return
        if delete_session(args.session_id):
            print_done(f"Session '{args.session_id}' deleted.")
        else:
            print_error(f"Session '{args.session_id}' not found.")

    elif args.action == "resume":
        if not args.session_id:
            print_error("Session ID required.")
            return
        data = get_session(args.session_id)
        if not data:
            print_error(f"Session '{args.session_id}' not found.")
            return
        messages = data.get("messages", [])
        last_user = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
            None,
        )
        if last_user:
            print_info(f"Resuming session with: {last_user[:100]}...")
        else:
            print_warning("No user message found.")


def cmd_config(args):
    """Show configuration"""
    from app.config import config

    llm_config = config.llm
    flat = {}
    for name, settings in llm_config.items():
        flat[f"llm.{name}.model"] = settings.model
        flat[f"llm.{name}.base_url"] = settings.base_url
        api_key = settings.api_key
        flat[f"llm.{name}.api_key"] = (api_key[:8] + "...") if api_key else "<not set>"
        flat[f"llm.{name}.max_tokens"] = settings.max_tokens
        flat[f"llm.{name}.temperature"] = settings.temperature

    sandbox = config.sandbox
    if sandbox:
        flat["sandbox.use_sandbox"] = sandbox.use_sandbox
        flat["sandbox.image"] = sandbox.image

    browser = config.browser_config
    if browser:
        flat["browser.headless"] = browser.headless

    mcp = config.mcp_config
    if mcp:
        flat["mcp.servers"] = str(list(mcp.servers.keys())) if mcp.servers else "[]"

    print_config_table(flat)
    print_info(f"\nConfig file: {config._get_config_path()}")


def cmd_models(args):
    """List configured models"""
    from app.config import config

    llm_config = config.llm
    models = []
    for name, settings in llm_config.items():
        models.append((
            name,
            {
                "model": settings.model,
                "base_url": settings.base_url,
                "api_key": settings.api_key,
            },
        ))
    if not models:
        print_warning("No models configured.")
        return
    print_models_table(models)
    print_info(f"Total: {len(models)} model(s) configured")


async def cmd_serve(args):
    """Start HTTP API server"""
    try:
        import uvicorn
    except ImportError:
        print_error("uvicorn required. pip install uvicorn")
        return

    host = args.host or "127.0.0.1"
    port = args.port or 8000
    app_path = args.app or "app.mcp.server:app"

    print_info(f"Starting server at http://{host}:{port}")
    print_info(f"App: {app_path}")
    print_info("Press Ctrl+C to stop")

    config_obj = uvicorn.Config(app_path, host=host, port=port, log_level="info")
    server = uvicorn.Server(config_obj)
    try:
        await server.serve()
    except KeyboardInterrupt:
        print_info("\nServer stopped.")


def cmd_version(args):
    """Show version"""
    try:
        from importlib.metadata import version as _ver
        ver = _ver("openmanus")
    except Exception:
        ver = "0.2.0"

    from app.config import config

    print_banner()
    print_info(f"Version: {ver}")
    print_info(f"Python: {sys.version.split()[0]}")
    print_info(f"Config: {config._get_config_path()}")


async def cmd_mcp(args):
    """Manage MCP servers"""
    from app.config import config

    mcp_config = config.mcp_config
    if args.action == "list":
        if not mcp_config.servers:
            print_info("No MCP servers configured.")
            return
        print_info(f"\nMCP Servers ({len(mcp_config.servers)}):")
        for sid, sc in mcp_config.servers.items():
            conn_type = sc.type
            target = sc.url or sc.command or ""
            print_info(f"  {sid}: ({conn_type}) {target}")

    elif args.action == "connect":
        from app.agent.mcp import MCPAgent

        agent = MCPAgent()
        try:
            conn_type = args.connection_type or "stdio"
            server_url = args.url
            print_info(f"Connecting via {conn_type}...")
            if conn_type == "stdio":
                cmd = args.command or sys.executable
                await agent.initialize(
                    connection_type="stdio",
                    command=cmd,
                    args=args.args or [],
                )
            else:
                await agent.initialize(connection_type="sse", server_url=server_url)

            print_done("Connected to MCP server")
            if args.prompt:
                print_info(f"Running: {args.prompt}")
                result = await agent.run(args.prompt)
                print_info(f"Result: {str(result)[:500]}")
            else:
                print_info('Interactive MCP mode ("exit" to quit)')
                while True:
                    p = input_with_prompt("Enter request")
                    if p.lower() in ("exit", "quit", "q"):
                        break
                    result = await agent.run(p)
                    print_info(f"\nAgent: {str(result)[:500]}")
        except KeyboardInterrupt:
            print_info("\nInterrupted.")
        except Exception as e:
            print_error(f"MCP Error: {e}")
        finally:
            await agent.cleanup()


async def cmd_web(args):
    """Start web interface"""
    print_info("Launching HTTP server for web interface...")
    await cmd_serve(args)


def cmd_providers(args):
    """Manage AI providers"""
    if args.action == "list":
        providers = _list_providers()
        print_providers_table(providers)
        print_info(f"Total: {len(providers)} provider(s)")

    elif args.action == "add":
        name = args.name
        model = args.model or ""
        base_url = args.base_url or ""
        api_key = args.api_key or ""

        if not api_key:
            api_key = os.environ.get(f"{name.upper()}_API_KEY", "")

        if not base_url and name.lower() in KNOWN_PROVIDERS:
            base_url = KNOWN_PROVIDERS[name.lower()]["base_url"]

        if not model and name.lower() in KNOWN_PROVIDERS:
            models = KNOWN_PROVIDERS[name.lower()]["models"]
            model = models[0] if models else ""

        if not base_url:
            base_url = input_with_prompt("Base URL")
        if not model:
            model = input_with_prompt("Model name")
        if not api_key:
            api_key = input_with_prompt("API key")

        _add_provider(name, model, base_url, api_key, set_default=args.default)
        print_done(f"Provider '{name}' added.")

    elif args.action == "remove":
        if not args.name:
            print_error("Provider name required.")
            return
        if not confirm_action(f"Remove provider '{args.name}'?"):
            return
        if _remove_provider(args.name):
            print_done(f"Provider '{args.name}' removed.")
        else:
            print_error(f"Provider '{args.name}' not found.")

    elif args.action == "set-default":
        if not args.name:
            print_error("Provider name required.")
            return
        if _set_default_provider(args.name):
            print_done(f"Default provider set to '{args.name}'.")
        else:
            print_error(f"Provider '{args.name}' not found. Add it first.")


def cmd_agent(args):
    """Manage agents"""
    known_agents = [
        {"name": "manus", "description": "General-purpose agent with browser, code, and file tools", "is_default": True},
        {"name": "data_analysis", "description": "Data analysis and visualization agent", "is_default": False},
        {"name": "swe", "description": "Software engineering agent", "is_default": False},
    ]

    if args.action == "list":
        print_agents_table(known_agents)
        print_info(f"Total: {len(known_agents)} agent(s)")

    elif args.action == "use":
        if not args.name:
            print_error("Agent name required.")
            return
        names = [a["name"] for a in known_agents]
        if args.name not in names:
            print_error(f"Unknown agent '{args.name}'. Known: {', '.join(names)}")
            return
        print_info(f"Using agent: {args.name}")

    elif args.action == "create":
        print_info("Custom agent creation not yet supported.")


def cmd_stats(args):
    """Show usage statistics"""
    stats = usage_stats.get_summary()
    print_stats_table(stats)
    if args.reset:
        if confirm_action("Reset all usage statistics?"):
            usage_stats.reset()
            print_done("Statistics reset.")


def cmd_export(args):
    """Export session as JSON"""
    from cli.export_import import export_session

    session_id = args.session_id
    if not session_id:
        print_error("Session ID required.")
        return

    path = export_session(session_id, args.output)
    if path:
        print_export_result(session_id, path)
    else:
        print_error(f"Session '{session_id}' not found.")


def cmd_import(args):
    """Import session from JSON"""
    from cli.export_import import import_session

    path = args.file
    if not path:
        print_error("File path required.")
        return

    result = import_session(path)
    if result:
        print_done(f"Imported session {result['id'][:8]} ({result['messages']} messages)")
    else:
        print_error(f"Could not import from '{path}'.")


async def cmd_attach(args):
    """Attach to a running server"""
    from cli.attach import attach_to_server

    url = args.url
    if not url:
        print_error("Server URL required.")
        return

    await attach_to_server(url, session_id=args.session, prompt=args.prompt)


def cmd_debug(args):
    """Debugging and troubleshooting"""
    if args.action == "info":
        info = collect_debug_info()
        print_debug_info(info)

    elif args.action == "system":
        info = get_system_info()
        print_debug_info(info)

    elif args.action == "config":
        info = get_config_info()
        print_debug_info(info)

    elif args.action == "env":
        info = get_env_info()
        print_debug_info(info)

    elif args.action == "network":
        from cli.debug import get_network_info
        info = get_network_info()
        print_debug_info(info)

    elif args.action == "deps":
        deps = check_dependencies()
        for d in deps:
            status = "[green]ok[/]" if d["status"] == "ok" else f"[red]{d['status']}[/]"
            print_info(f"  {d['name']}: {status} {d['version']}")

    else:
        print_info("Debug commands: info, system, config, env, network, deps")


def cmd_completion(args):
    """Generate shell completion script"""
    shell = args.shell or "bash"
    scripts = {
        "bash": generate_bash_completion,
        "zsh": generate_zsh_completion,
        "fish": generate_fish_completion,
    }

    if shell == "install":
        result = install_completion(args.shell_type or "auto")
        print_info(result)
        return

    if shell not in scripts:
        print_error(f"Unsupported shell: {shell}. Use: bash, zsh, fish")
        return

    print(scripts[shell]().strip())


def cmd_upgrade(args):
    """Upgrade OpenManus"""
    target = args.target or "latest"
    print_info(f"Attempting to upgrade to {target}...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "-e", "."],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent,
        )
        if result.returncode == 0:
            print_done("Upgrade complete.")
        else:
            print_error(f"Upgrade failed: {result.stderr[:200]}")
    except Exception as e:
        print_error(f"Upgrade error: {e}")


def cmd_uninstall(args):
    """Uninstall OpenManus"""
    if not confirm_action("Uninstall OpenManus and remove all data?", default=False):
        return
    print_info("Uninstalling...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "uninstall", "openmanus", "-y"],
            capture_output=True,
        )
    except Exception:
        pass
    config_dir = Path.home() / ".openmanus"
    if config_dir.exists():
        shutil.rmtree(config_dir)
    print_done("OpenManus uninstalled.")


def cmd_plugin(args):
    """Manage plugins"""
    if args.action == "list":
        plugins = _list_plugins()
        if not plugins:
            print_info("No plugins installed.")
            return
        for p in plugins:
            status = "[green]enabled[/]" if p["enabled"] else "[red]disabled[/]"
            print_info(f"  {p['name']}: {p['description']} ({status})")

    elif args.action == "install":
        if not args.module:
            print_error("Module name required.")
            return
        success, msg = _install_plugin(args.module)
        if success:
            print_done(msg)
        else:
            print_error(msg)

    elif args.action == "remove":
        if not args.name:
            print_error("Plugin name required.")
            return
        success, msg = _remove_plugin(args.name)
        if success:
            print_done(msg)
        else:
            print_error(msg)


def cmd_db(args):
    """Database tools"""
    if args.action == "tables":
        print_info("Database tables:")
        tables = [
            "sessions  - JSON files in ~/.openmanus/sessions/",
            "stats     - ~/.openmanus/stats.json",
            "providers - ~/.openmanus/providers.json",
            "plugins   - ~/.openmanus/plugins/index.json",
        ]
        for t in tables:
            print_info(f"  {t}")

    elif args.action == "query":
        print_info("Query not yet implemented. Use 'session list' to browse sessions.")

    elif args.action == "inspect":
        data_dir = Path.home() / ".openmanus"
        if data_dir.exists():
            total_size = sum(f.stat().st_size for f in data_dir.rglob("*") if f.is_file())
            file_count = len(list(data_dir.rglob("*")))
            print_info(f"Data directory: {data_dir}")
            print_info(f"Files: {file_count}")
            print_info(f"Size: {total_size / 1024:.1f} KB")
        else:
            print_info("No OpenManus data directory found.")


def cmd_providers_opencode(args):
    """Parse opencode-style provider arg"""
    if args.provider:
        success, msg = add_opencode_provider(args.provider)
        if success:
            print_done(msg)
        else:
            print_error(msg)
