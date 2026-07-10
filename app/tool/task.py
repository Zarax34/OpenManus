import asyncio
from typing import Optional

from app.tool.base import BaseTool, ToolResult


SUB_AGENTS = {
    "general": {
        "class": "Manus",
        "description": "General-purpose agent for researching complex questions and executing multi-step tasks. Has full tool access.",
    },
    "explore": {
        "class": "SWEAgent",
        "description": "Fast agent for exploring codebases. Can search for files by patterns and answer questions about the codebase.",
    },
    "swe": {
        "class": "SWEAgent",
        "description": "Autonomous AI programmer that interacts directly with the computer to solve tasks.",
    },
}


_TASK_DESCRIPTION = """Delegate a task to a sub-agent and return its result.
Available agents: """ + ", ".join(f"{k} ({v['description']})" for k, v in SUB_AGENTS.items())


class Task(BaseTool):
    name: str = "task"
    description: str = _TASK_DESCRIPTION
    parameters: dict = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The task description to delegate to the sub-agent",
            },
            "agent": {
                "type": "string",
                "description": "The sub-agent to use: " + ", ".join(SUB_AGENTS.keys()),
                "enum": list(SUB_AGENTS.keys()),
            },
        },
        "required": ["prompt"],
    }

    async def execute(self, prompt: str, agent: str = "general") -> str:
        agent_def = SUB_AGENTS.get(agent)
        if not agent_def:
            available = ", ".join(SUB_AGENTS.keys())
            return f"Unknown agent '{agent}'. Available: {available}"

        class_name = agent_def["class"]
        try:
            if class_name == "Manus":
                from app.agent.manus import Manus as AgentClass
            elif class_name == "SWEAgent":
                from app.agent.swe import SWEAgent as AgentClass
            else:
                return f"Unknown agent class: {class_name}"

            sub_agent = AgentClass()
            result = await asyncio.wait_for(sub_agent.run(prompt), timeout=120)
            return str(result) if result else "No result"
        except asyncio.TimeoutError:
            return "Sub-agent timed out"
        except Exception as e:
            return f"Sub-agent error: {e}"
