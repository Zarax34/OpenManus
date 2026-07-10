import shlex

SUBCOMMANDS = [
    "run", "session", "config", "models", "serve", "web",
    "mcp", "version", "providers", "agent", "stats",
    "export", "import", "attach", "debug", "plugin",
    "upgrade", "uninstall", "completion", "db",
]

SESSION_SUBCOMMANDS = ["list", "show", "delete", "resume"]
MCP_SUBCOMMANDS = ["list", "connect"]
PROVIDER_SUBCOMMANDS = ["list", "add", "remove", "set-default"]
AGENT_SUBCOMMANDS = ["list", "use", "create"]
PLUGIN_SUBCOMMANDS = ["list", "install", "remove"]
DB_SUBCOMMANDS = ["query", "tables", "inspect"]
DEBUG_SUBCOMMANDS = ["info", "config", "env", "system", "network"]


def generate_bash_completion() -> str:
    return f"""# OpenManus bash completion
_openmanus_completions() {{
    local cur prev words cword
    _init_completion || return

    if [[ $cword -eq 1 ]]; then
        COMPREPLY=($(compgen -W "{' '.join(SUBCOMMANDS)}" -- "$cur"))
        return
    fi

    case "${{words[1]}}" in
        session)
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=($(compgen -W "{' '.join(SESSION_SUBCOMMANDS)}" -- "$cur"))
            fi
            ;;
        mcp)
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=($(compgen -W "{' '.join(MCP_SUBCOMMANDS)}" -- "$cur"))
            fi
            ;;
        providers)
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=($(compgen -W "{' '.join(PROVIDER_SUBCOMMANDS)}" -- "$cur"))
            fi
            ;;
        agent)
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=($(compgen -W "{' '.join(AGENT_SUBCOMMANDS)}" -- "$cur"))
            fi
            ;;
        plugin)
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=($(compgen -W "{' '.join(PLUGIN_SUBCOMMANDS)}" -- "$cur"))
            fi
            ;;
        db)
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=($(compgen -W "{' '.join(DB_SUBCOMMANDS)}" -- "$cur"))
            fi
            ;;
        debug)
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=($(compgen -W "{' '.join(DEBUG_SUBCOMMANDS)}" -- "$cur"))
            fi
            ;;
        run)
            if [[ "$cur" == -* ]]; then
                COMPREPLY=($(compgen -W "-s --session -m --model --auto --mini --no-replay" -- "$cur"))
            fi
            ;;
    esac
}}
complete -F _openmanus_completions openmanus
"""


def generate_zsh_completion() -> str:
    return f"""#compdef openmanus
typeset -A opt_args

_local_subcommands=(
    {' '.join(SUBCOMMANDS)}
)

_session_subcommands=(
    {' '.join(SESSION_SUBCOMMANDS)}
)

_mcp_subcommands=(
    {' '.join(MCP_SUBCOMMANDS)}
)

_provider_subcommands=(
    {' '.join(PROVIDER_SUBCOMMANDS)}
)

_agent_subcommands=(
    {' '.join(AGENT_SUBCOMMANDS)}
)

_plugin_subcommands=(
    {' '.join(PLUGIN_SUBCOMMANDS)}
)

_db_subcommands=(
    {' '.join(DB_SUBCOMMANDS)}
)

_debug_subcommands=(
    {' '.join(DEBUG_SUBCOMMANDS)}
)

_openmanus() {{
    local context state state_descr line
    typeset -A opt_args

    if [[ $current -eq 1 ]]; then
        _describe -t commands 'openmanus subcommand' _local_subcommands
        return
    fi

    case "$words[2]" in
        session) _describe -t commands 'session' _session_subcommands ;;
        mcp) _describe -t commands 'mcp' _mcp_subcommands ;;
        providers) _describe -t commands 'providers' _provider_subcommands ;;
        agent) _describe -t commands 'agent' _agent_subcommands ;;
        plugin) _describe -t commands 'plugin' _plugin_subcommands ;;
        db) _describe -t commands 'db' _db_subcommands ;;
        debug) _describe -t commands 'debug' _debug_subcommands ;;
        run) _arguments {{-s,--session}}[Session ID] {{-m,--model}}[Model to use] {{--auto}}[Auto-approve] {{--mini}}[Mini mode] {{--no-replay}}[Disable replay] ;;
    esac
}}

_openmanus
"""


def generate_fish_completion() -> str:
    subs = ' '.join(SUBCOMMANDS)
    items = ' '.join([f'{s}\\"Run {s} command"' for s in SUBCOMMANDS])
    ses = ' '.join(SESSION_SUBCOMMANDS)
    mcps = ' '.join(MCP_SUBCOMMANDS)
    provs = ' '.join(PROVIDER_SUBCOMMANDS)
    ags = ' '.join(AGENT_SUBCOMMANDS)
    plgs = ' '.join(PLUGIN_SUBCOMMANDS)
    dbs = ' '.join(DB_SUBCOMMANDS)
    dbgs = ' '.join(DEBUG_SUBCOMMANDS)
    return f"""# OpenManus fish completion
function __fish_openmanus_using_command
    set -l cmd (commandline -opc)
    if [ (count $cmd) -gt 1 ]
        contains -- $cmd[2] $argv
    end
end

# Subcommands
complete -f -c openmanus -n "not __fish_seen_subcommand_from {subs}" -a "{items}"

# Session subcommands
complete -f -c openmanus -n "__fish_openmanus_using_command session" -a "{ses}"

# MCP subcommands
complete -f -c openmanus -n "__fish_openmanus_using_command mcp" -a "{mcps}"

# Provider subcommands
complete -f -c openmanus -n "__fish_openmanus_using_command providers" -a "{provs}"

# Agent subcommands
complete -f -c openmanus -n "__fish_openmanus_using_command agent" -a "{ags}"

# Plugin subcommands
complete -f -c openmanus -n "__fish_openmanus_using_command plugin" -a "{plgs}"

# DB subcommands
complete -f -c openmanus -n "__fish_openmanus_using_command db" -a "{dbs}"

# Debug subcommands
complete -f -c openmanus -n "__fish_openmanus_using_command debug" -a "{dbgs}"

# Options
complete -f -c openmanus -n "__fish_openmanus_using_command run" -s s -l session -d "Session ID"
complete -f -c openmanus -n "__fish_openmanus_using_command run" -s m -l model -d "Model to use"
complete -f -c openmanus -n "__fish_openmanus_using_command run" -l auto -d "Auto-approve"
complete -f -c openmanus -n "__fish_openmanus_using_command run" -l mini -d "Mini mode"
"""


def install_completion(shell: str = "auto") -> str:
    import subprocess
    import os

    if shell == "auto":
        shell = os.environ.get("SHELL", "/bin/bash")
        if "zsh" in shell:
            shell = "zsh"
        elif "fish" in shell:
            shell = "fish"
        else:
            shell = "bash"

    scripts = {
        "bash": (generate_bash_completion(), "~/.bashrc"),
        "zsh": (generate_zsh_completion(), "~/.zshrc"),
        "fish": (generate_fish_completion(), "~/.config/fish/completions/openmanus.fish"),
    }

    if shell not in scripts:
        return f"Unsupported shell: {shell}. Supported: bash, zsh, fish"

    script, rc_file = scripts[shell]

    if shell == "fish":
        os.makedirs(os.path.expanduser("~/.config/fish/completions"), exist_ok=True)
        dest = os.path.expanduser("~/.config/fish/completions/openmanus.fish")
        with open(dest, "w") as f:
            f.write(script)
        return f"Fish completion installed to {dest}"
    else:
        rc_path = os.path.expanduser(rc_file)
        marker = "# openmanus completion"
        if marker in open(rc_path).read() if os.path.exists(rc_path) else "":
            return f"Completion already installed in {rc_file}"
        with open(rc_path, "a") as f:
            f.write(f"\n{marker}\n{script}\n")
        return f"Completion installed. Restart your shell or run: source {rc_file}"
