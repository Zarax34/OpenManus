import os
import re
from pathlib import Path
from typing import List, Optional

from app.tool.base import BaseTool, ToolResult


SKILL_DIRS = [
    Path.home() / ".config" / "opencode" / "skills",
    Path.home() / ".agents" / "skills",
    Path.home() / ".claude" / "skills",
    Path(".opencode") / "skills",
    Path(".agents") / "skills",
    Path(".claude") / "skills",
]


def _discover_skills() -> list[dict]:
    found: dict[str, dict] = {}
    for base in SKILL_DIRS:
        if not base.exists():
            continue
        for skill_dir in base.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            name = skill_dir.name
            if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", name):
                continue
            try:
                content = skill_file.read_text(encoding="utf-8")
            except Exception:
                continue
            description = ""
            name_in_fm = ""
            for line in content.splitlines():
                if line.startswith("name:"):
                    name_in_fm = line.split(":", 1)[1].strip()
                elif line.startswith("description:"):
                    description = line.split(":", 1)[1].strip()
                if line == "---" and name_in_fm:
                    break
            display_name = name_in_fm or name
            found[name] = {
                "name": display_name,
                "description": description or name,
                "path": str(skill_file),
                "content": content,
            }
    return list(found.values())


_SKILL_DESCRIPTION = """Discover and load SKILL.md definitions from standard locations.
Search paths: .opencode/skills/, .agents/skills/, .claude/skills/, 
~/.config/opencode/skills/, ~/.agents/skills/, ~/.claude/skills/

Returns available skills with their names and descriptions when listing.
When loading a skill, returns the full SKILL.md content."""


class Skill(BaseTool):
    name: str = "skill"
    description: str = _SKILL_DESCRIPTION
    parameters: dict = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the skill to load. Omit to list all available skills.",
            }
        },
    }

    async def execute(self, name: Optional[str] = None) -> str:
        skills = _discover_skills()
        if not skills:
            return "No skills found in any standard location."

        if name:
            for s in skills:
                if s["name"] == name:
                    return f"---\nname: {s['name']}\ndescription: {s['description']}\n---\n\n{s['content']}"
            available = ", ".join(s["name"] for s in skills)
            return f"Skill '{name}' not found. Available skills: {available}"

        lines = ["<available_skills>"]
        for s in skills:
            lines.append("  <skill>")
            lines.append(f"    <name>{s['name']}</name>")
            lines.append(f"    <description>{s['description']}</description>")
            lines.append("  </skill>")
        lines.append("</available_skills>")
        return "\n".join(lines)
