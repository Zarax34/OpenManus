import json
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

STATS_DIR = Path.home() / ".openmanus"
STATS_FILE = STATS_DIR / "stats.json"

_lock = threading.Lock()


class UsageStats:
    def __init__(self):
        self._load()

    def _load(self):
        with _lock:
            if STATS_FILE.exists():
                try:
                    with open(STATS_FILE) as f:
                        data = json.load(f)
                    self.total_tokens = data.get("total_tokens", 0)
                    self.prompt_tokens = data.get("prompt_tokens", 0)
                    self.completion_tokens = data.get("completion_tokens", 0)
                    self.total_cost = data.get("total_cost", 0.0)
                    self.total_sessions = data.get("total_sessions", 0)
                    self.total_calls = data.get("total_calls", 0)
                    self.sessions_today = data.get("sessions_today", 0)
                    self.last_reset = data.get("last_reset", "")
                    self.history = data.get("history", [])
                    return
                except (json.JSONDecodeError, KeyError):
                    pass
            self._reset()

    def _reset(self):
        self.total_tokens = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_cost = 0.0
        self.total_sessions = 0
        self.total_calls = 0
        self.sessions_today = 0
        self.last_reset = datetime.now().isoformat()
        self.history = []

    def _save(self):
        STATS_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "total_tokens": self.total_tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_cost": self.total_cost,
            "total_sessions": self.total_sessions,
            "total_calls": self.total_calls,
            "sessions_today": self.sessions_today,
            "last_reset": self.last_reset,
            "history": self.history[-1000:],
        }
        with open(STATS_FILE, "w") as f:
            json.dump(data, f, indent=2)

    def track_call(self, prompt_tokens: int = 0, completion_tokens: int = 0, cost: float = 0.0):
        with _lock:
            self.total_calls += 1
            self.prompt_tokens += prompt_tokens
            self.completion_tokens += completion_tokens
            self.total_tokens += prompt_tokens + completion_tokens
            self.total_cost += cost
            self.history.append({
                "timestamp": datetime.now().isoformat(),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost": cost,
            })
            self._save()

    def track_session(self):
        with _lock:
            self.total_sessions += 1
            self.sessions_today += 1
            self._save()

    def get_summary(self) -> dict:
        with _lock:
            now = datetime.now()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_calls = sum(
                1 for h in self.history
                if datetime.fromisoformat(h["timestamp"]) >= today_start
            )
            today_cost = sum(
                h.get("cost", 0) for h in self.history
                if datetime.fromisoformat(h["timestamp"]) >= today_start
            )
            today_tokens = sum(
                h.get("prompt_tokens", 0) + h.get("completion_tokens", 0)
                for h in self.history
                if datetime.fromisoformat(h["timestamp"]) >= today_start
            )
            return {
                "Total Calls": self.total_calls,
                "Total Tokens": self.total_tokens,
                "Prompt Tokens": self.prompt_tokens,
                "Completion Tokens": self.completion_tokens,
                "Total Cost ($)": f"{self.total_cost:.6f}",
                "Total Sessions": self.total_sessions,
                "Today Calls": today_calls,
                "Today Tokens": today_tokens,
                "Today Cost ($)": f"{today_cost:.6f}",
                "History Entries": len(self.history),
            }

    def reset(self):
        with _lock:
            self.total_tokens = 0
            self.prompt_tokens = 0
            self.completion_tokens = 0
            self.total_cost = 0.0
            self.total_calls = 0
            self.sessions_today = 0
            self.last_reset = datetime.now().isoformat()
            self.history = []
            self._save()


usage_stats = UsageStats()
