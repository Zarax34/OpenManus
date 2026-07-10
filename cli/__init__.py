#!/usr/bin/env python3
import argparse
import asyncio
import shutil
import sys

import os

from cli.commands import (
    run_interactive,
    run_single,
    cmd_session,
    cmd_config,
    cmd_models,
    cmd_serve,
    cmd_version,
    cmd_mcp,
    cmd_web,
    cmd_providers,
    cmd_agent,
    cmd_stats,
    cmd_export,
    cmd_import,
    cmd_attach,
    cmd_debug,
    cmd_completion,
    cmd_upgrade,
    cmd_uninstall,
    cmd_plugin,
    cmd_db,
)
from cli.setup import is_first_run, run_setup
from cli.ui import print_banner, print_info, print_error

BANNER = r"""
   ⠀                                ▄
   █▀▀█ █▀▀█ █▀▀█ █▀▀▄ █▀▀▀ █▀▀█ █▀▀█ █▀▀█
   █  █ █  █ █▀▀▀ █  █ █    █  █ █  █ █▀▀▀
   ▀▀▀▀ █▀▀▀ ▀▀▀▀ ▀  ▀ ▀▀▀▀ ▀▀▀▀ ▀▀▀▀ ▀▀▀▀
"""


class CustomHelpAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        _print_help(parser)
        sys.exit(0)


def _print_help(parser):
    cols = shutil.get_terminal_size().columns
    margin = 2
    cmd_col = 20
    max_desc = cols - margin - cmd_col - margin - margin

    print(BANNER)
    print("Commands:")

    commands = [
        ("completion", "generate shell completion script"),
        ("config", "show configuration"),
        ("debug", "debugging and troubleshooting tools"),
        ("mcp", "manage MCP servers"),
        ("models [provider]", "list all available models"),
        ("plugin <module>", "install plugin and update config", "plug"),
        ("providers", "manage AI providers and credentials", "auth"),
        ("agent", "manage agents"),
        ("session", "manage sessions"),
        ("stats", "show token usage and cost statistics"),
        ("serve", "starts a headless OpenManus server"),
        ("web", "start OpenManus server and open web interface"),
        ("run [message..]", "run OpenManus with a message"),
        ("attach <url>", "attach to a running OpenManus server"),
        ("export [sessionID]", "export session data as JSON"),
        ("import <file>", "import session data from JSON file or URL"),
        ("upgrade [target]", "upgrade OpenManus to the latest or a specific version"),
        ("uninstall", "uninstall OpenManus and remove all related files"),
        ("db", "database tools"),
        ("version", "show version information"),
    ]

    for entry in commands:
        cmd = entry[0]
        desc = entry[1]
        alias = entry[2] if len(entry) > 2 else None
        if alias:
            desc += f"  [aliases: {alias}]"
        padded = cmd.ljust(cmd_col)
        print(f"  openmanus {padded}  {desc}")

    print()
    print("Positionals:")
    print(f"  {'project':<{cmd_col}}  {'path to start openmanus in':<{max_desc}}  [string]")

    print()
    print("Options:")
    options = [
        ("-h, --help", "show help", "[boolean]"),
        ("-v, --version", "show version number", "[boolean]"),
        ("--print-logs", "print logs to stderr", "[boolean]"),
        ("--log-level", "log level", "[string] [choices: \"DEBUG\", \"INFO\", \"WARN\", \"ERROR\"]"),
        ("--pure", "run without external plugins", "[boolean]"),
        ("--port", "port to listen on", "[number] [default: 0]"),
        ("--hostname", "hostname to listen on", '[string] [default: "127.0.0.1"]'),
        ("--mdns", "enable mDNS service discovery (defaults hostname to 0.0.0.0)", "[boolean] [default: false]"),
        ("--mdns-domain", "custom domain name for mDNS service", '[string] [default: "openmanus.local"]'),
        ("--cors", "additional domains to allow for CORS", "[array] [default: []]"),
        ("-m, --model", "model to use in the format of provider/model", "[string]"),
        ("-c, --continue", "continue the last session", "[boolean]"),
        ("-s, --session", "session id to continue", "[string]"),
        ("--fork", "fork the session when continuing (use with --continue or --session)", "[boolean]"),
        ("--prompt", "prompt to use", "[string]"),
        ("--agent", "agent to use", "[string]"),
        ("--auto", "auto-approve permissions that are not explicitly denied (dangerous!)", "[boolean] [default: false]"),
        ("--mini", "start the minimal interactive interface", "[boolean] [default: false]"),
        ("--no-replay", "disable mini session history replay on resume and after resize", "[boolean]"),
        ("--replay-limit", "cap visible mini replay to the newest N messages", "[number]"),
    ]

    opt_col = max(len(o[0]) for o in options) + 2
    annot_col = max(len(o[2]) for o in options) + 1
    desc_col = cols - margin - opt_col - margin - annot_col - margin
    if desc_col < 20:
        desc_col = 20
    for flag, desc, annotation in options:
        padded = flag.ljust(opt_col)
        desc_short = desc[:desc_col] if len(desc) > desc_col else desc
        print(f"  {padded}  {desc_short:<{desc_col}}  {annotation}")

    print()
    print("Run 'openmanus <command> --help' for more details on a command.")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="openmanus",
        usage=argparse.SUPPRESS,
        description="OpenManus - Open source AI agent for general-purpose tasks",
        epilog="Run 'openmanus <command> --help' for more details on a command.",
        add_help=False,
    )
    parser.add_argument("-h", "--help", action=CustomHelpAction, nargs=0, help="show help")

    # Global options
    parser.add_argument(
        "-v", "--version", action="store_true", help="show version number"
    )
    parser.add_argument(
        "--print-logs", action="store_true", help="print logs to stderr"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARN", "ERROR"],
        default=None,
        help="log level",
    )
    parser.add_argument(
        "--pure",
        action="store_true",
        help="run without external plugins",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="port to listen on",
    )
    parser.add_argument(
        "--hostname",
        default="127.0.0.1",
        help="hostname to listen on",
    )
    parser.add_argument(
        "--mdns",
        action="store_true",
        default=False,
        help="enable mDNS service discovery",
    )
    parser.add_argument(
        "--mdns-domain",
        default="openmanus.local",
        help="custom domain name for mDNS service",
    )
    parser.add_argument(
        "--cors",
        action="append",
        default=[],
        help="additional domains to allow for CORS",
    )
    parser.add_argument(
        "-m", "--model",
        help="model to use in the format of provider/model",
    )
    parser.add_argument(
        "-c", "--continue",
        dest="continue_session",
        action="store_true",
        help="continue the last session",
    )
    parser.add_argument(
        "-s", "--session",
        help="session id to continue",
    )
    parser.add_argument(
        "--fork",
        action="store_true",
        help="fork the session when continuing",
    )
    parser.add_argument(
        "--prompt",
        help="prompt to use",
    )
    parser.add_argument(
        "--agent",
        help="agent to use",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="auto-approve permissions (dangerous!)",
    )
    parser.add_argument(
        "--mini",
        action="store_true",
        default=False,
        help="start the minimal interactive interface",
    )
    parser.add_argument(
        "--no-replay",
        action="store_true",
        default=False,
        help="disable mini session history replay on resume and after resize",
    )
    parser.add_argument(
        "--replay-limit",
        type=int,
        help="cap visible mini replay to the newest N messages",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run
    run_parser = subparsers.add_parser("run", help="Run agent with a prompt")
    run_parser.add_argument("prompt", nargs="?", default=None, help="Prompt to process")
    run_parser.add_argument("-s", "--session", help="Session ID to continue from")
    run_parser.add_argument("-m", "--model", help="Model to use")
    run_parser.add_argument("--auto", action="store_true", help="Auto-approve tools")
    run_parser.add_argument("--mini", action="store_true", help="Mini output mode")
    run_parser.add_argument("--no-replay", action="store_true", help="Disable replay")

    # session
    session_parser = subparsers.add_parser("session", help="Manage sessions")
    session_sub = session_parser.add_subparsers(dest="action")
    session_list = session_sub.add_parser("list", help="List all sessions")
    session_show = session_sub.add_parser("show", help="Show session details")
    session_show.add_argument("session_id", help="Session ID (full or prefix)")
    session_delete = session_sub.add_parser("delete", help="Delete a session")
    session_delete.add_argument("session_id", help="Session ID (full or prefix)")
    session_resume = session_sub.add_parser("resume", help="Resume a session")
    session_resume.add_argument("session_id", help="Session ID (full or prefix)")

    # config
    config_parser = subparsers.add_parser("config", help="Show configuration")

    # models
    models_parser = subparsers.add_parser("models", help="List configured models")
    models_parser.add_argument("provider", nargs="?", help="Filter by provider name")

    # serve
    serve_parser = subparsers.add_parser("serve", help="Start HTTP API server")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port to listen")
    serve_parser.add_argument("--app", default="app.mcp.server:app", help="App module")

    # web
    web_parser = subparsers.add_parser("web", help="Start web interface")
    web_parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    web_parser.add_argument("--port", type=int, default=8000, help="Port to listen")

    # mcp
    mcp_parser = subparsers.add_parser("mcp", help="Manage MCP servers")
    mcp_sub = mcp_parser.add_subparsers(dest="action")
    mcp_list = mcp_sub.add_parser("list", help="List configured MCP servers")
    mcp_connect = mcp_sub.add_parser("connect", help="Connect to MCP server")
    mcp_connect.add_argument("-c", "--connection-type", choices=["stdio", "sse"], default="stdio")
    mcp_connect.add_argument("-u", "--url", help="Server URL for SSE connection")
    mcp_connect.add_argument("--command", help="Command for stdio connection")
    mcp_connect.add_argument("--args", nargs="*", default=[])
    mcp_connect.add_argument("-p", "--prompt", help="Prompt to send after connecting")

    # providers
    providers_parser = subparsers.add_parser("providers", aliases=["auth"], help="Manage AI providers and credentials")
    prov_sub = providers_parser.add_subparsers(dest="action")
    prov_list = prov_sub.add_parser("list", help="List configured providers")
    prov_add = prov_sub.add_parser("add", help="Add a provider")
    prov_add.add_argument("name", help="Provider name")
    prov_add.add_argument("-m", "--model", help="Model name")
    prov_add.add_argument("-u", "--base-url", help="Base URL")
    prov_add.add_argument("-k", "--api-key", help="API key")
    prov_add.add_argument("--default", action="store_true", help="Set as default")
    prov_remove = prov_sub.add_parser("remove", help="Remove a provider")
    prov_remove.add_argument("name", help="Provider name")
    prov_default = prov_sub.add_parser("set-default", help="Set default provider")
    prov_default.add_argument("name", help="Provider name")

    # agent
    agent_parser = subparsers.add_parser("agent", help="Manage agents")
    agent_sub = agent_parser.add_subparsers(dest="action")
    agent_list = agent_sub.add_parser("list", help="List available agents")
    agent_use = agent_sub.add_parser("use", help="Select an agent to use")
    agent_use.add_argument("name", help="Agent name")
    agent_create = agent_sub.add_parser("create", help="Create a custom agent")
    agent_create.add_argument("name", nargs="?", help="Agent name")

    # stats
    stats_parser = subparsers.add_parser("stats", help="Show token usage and cost statistics")
    stats_parser.add_argument("--reset", action="store_true", help="Reset statistics")

    # export
    export_parser = subparsers.add_parser("export", help="Export session data as JSON")
    export_parser.add_argument("session_id", help="Session ID to export")
    export_parser.add_argument("-o", "--output", help="Output file path")

    # import
    import_parser = subparsers.add_parser("import", help="Import session data from JSON file")
    import_parser.add_argument("file", help="JSON file path or URL")

    # attach
    attach_parser = subparsers.add_parser("attach", help="Attach to a running server")
    attach_parser.add_argument("url", help="Server URL to attach to")
    attach_parser.add_argument("-s", "--session", help="Session ID")
    attach_parser.add_argument("-p", "--prompt", help="Prompt to send")

    # debug
    debug_parser = subparsers.add_parser("debug", help="Debugging and troubleshooting tools")
    debug_sub = debug_parser.add_subparsers(dest="action")
    debug_sub.add_parser("info", help="Collect all debug info")
    debug_sub.add_parser("system", help="Show system info")
    debug_sub.add_parser("config", help="Show config debug info")
    debug_sub.add_parser("env", help="Show environment variables")
    debug_sub.add_parser("network", help="Check network connectivity")
    debug_sub.add_parser("deps", help="Check dependencies")

    # completion
    completion_parser = subparsers.add_parser("completion", help="Generate shell completion script")
    completion_parser.add_argument("shell", nargs="?", choices=["bash", "zsh", "fish", "install"], default="bash",
                                  help="Shell type")
    completion_parser.add_argument("shell_type", nargs="?", help="Shell type for install")

    # upgrade
    upgrade_parser = subparsers.add_parser("upgrade", help="Upgrade OpenManus to the latest version")
    upgrade_parser.add_argument("target", nargs="?", default="latest", help="Target version")

    # uninstall
    uninstall_parser = subparsers.add_parser("uninstall", help="Uninstall OpenManus and remove all related files")

    # plugin
    plugin_parser = subparsers.add_parser("plugin", aliases=["plug"], help="Manage plugins")
    plugin_sub = plugin_parser.add_subparsers(dest="action")
    plugin_sub.add_parser("list", help="List installed plugins")
    plugin_install = plugin_sub.add_parser("install", help="Install a plugin")
    plugin_install.add_argument("module", help="Module name to install")
    plugin_remove = plugin_sub.add_parser("remove", help="Remove a plugin")
    plugin_remove.add_argument("name", help="Plugin name")

    # db
    db_parser = subparsers.add_parser("db", help="Database tools")
    db_sub = db_parser.add_subparsers(dest="action")
    db_sub.add_parser("tables", help="List database tables")
    db_sub.add_parser("query", help="Run a query")
    db_sub.add_parser("inspect", help="Inspect database")

    # version
    version_parser = subparsers.add_parser("version", help="Show version information")

    return parser


async def async_main():
    parser = build_parser()
    args = parser.parse_args()

    if args.version:
        cmd_version(args)
        return

    if args.log_level:
        from app.logger import define_log_level
        define_log_level(print_level=args.log_level)

    # Default: interactive mode
    if not args.command:
        if is_first_run():
            try:
                run_setup()
            except Exception as e:
                print_error(f"Setup error: {e}")
            return
        if args.prompt:
            await run_single(args)
        else:
            await run_interactive(args)
        return

    command = args.command
    cmds = {
        "run": run_single,
        "session": None,
        "config": None,
        "models": None,
        "serve": cmd_serve,
        "web": cmd_web,
        "mcp": cmd_mcp,
        "providers": None,
        "auth": None,
        "agent": None,
        "stats": None,
        "export": None,
        "import": None,
        "attach": cmd_attach,
        "debug": None,
        "completion": None,
        "upgrade": None,
        "uninstall": None,
        "plugin": None,
        "plug": None,
        "db": None,
        "version": None,
    }

    handler = cmds.get(command)
    if handler:
        await handler(args)
    elif command in ("session",):
        cmd_session(args)
    elif command in ("config",):
        cmd_config(args)
    elif command in ("models",):
        cmd_models(args)
    elif command in ("providers", "auth"):
        cmd_providers(args)
    elif command in ("agent",):
        cmd_agent(args)
    elif command in ("stats",):
        cmd_stats(args)
    elif command in ("export",):
        cmd_export(args)
    elif command in ("import",):
        cmd_import(args)
    elif command in ("debug",):
        cmd_debug(args)
    elif command in ("completion",):
        cmd_completion(args)
    elif command in ("upgrade",):
        cmd_upgrade(args)
    elif command in ("uninstall",):
        cmd_uninstall(args)
    elif command in ("plugin", "plug"):
        cmd_plugin(args)
    elif command in ("db",):
        cmd_db(args)
    elif command in ("version",):
        cmd_version(args)
    else:
        print_banner()
        parser.print_help()


def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print_info("\nInterrupted.")
        sys.exit(0)
    except Exception as e:
        print_error(f"Error: {e}")
        if "--print-logs" in sys.argv:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
