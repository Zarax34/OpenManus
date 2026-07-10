import json
import os
import uuid
from datetime import datetime
from pathlib import Path

SESSION_DIR = Path.home() / ".openmanus" / "sessions"


def _ensure_dir():
    SESSION_DIR.mkdir(parents=True, exist_ok=True)


def create_session() -> str:
    _ensure_dir()
    session_id = str(uuid.uuid4())
    session = {
        "id": session_id,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "messages": [],
        "message_count": 0,
    }
    with open(SESSION_DIR / f"{session_id}.json", "w") as f:
        json.dump(session, f, indent=2)
    return session_id


def save_session(session_id: str, messages: list):
    _ensure_dir()
    path = SESSION_DIR / f"{session_id}.json"
    try:
        if path.exists():
            with open(path) as f:
                session = json.load(f)
        else:
            session = {
                "id": session_id,
                "created_at": datetime.now().isoformat(),
            }
        session["updated_at"] = datetime.now().isoformat()
        session["messages"] = [
            m if isinstance(m, dict) else m.model_dump() for m in messages
        ]
        session["message_count"] = len(session["messages"])
        with open(path, "w") as f:
            json.dump(session, f, indent=2)
        return True
    except Exception:
        return False


def list_sessions() -> list:
    _ensure_dir()
    sessions = []
    for f in sorted(SESSION_DIR.glob("*.json"), reverse=True):
        try:
            with open(f) as fh:
                data = json.load(fh)
                messages = data.get("messages", [])
                preview = ""
                for msg in reversed(messages):
                    if msg.get("role") == "user" and msg.get("content"):
                        preview = msg["content"]
                        break
                sessions.append(
                    {
                        "id": data["id"],
                        "created_at": data.get("created_at", ""),
                        "message_count": len(messages),
                        "preview": preview,
                    }
                )
        except (json.JSONDecodeError, KeyError):
            continue
    return sessions


def get_session(session_id: str) -> dict | None:
    _ensure_dir()
    path = SESSION_DIR / f"{session_id}.json"
    if not path.exists():
        for f in SESSION_DIR.glob("*.json"):
            with open(f) as fh:
                data = json.load(fh)
                if data["id"].startswith(session_id):
                    return data
        return None
    try:
        with open(path) as fh:
            return json.load(fh)
    except json.JSONDecodeError:
        return None


def delete_session(session_id: str) -> bool:
    _ensure_dir()
    path = SESSION_DIR / f"{session_id}.json"
    if path.exists():
        path.unlink()
        return True
    for f in SESSION_DIR.glob("*.json"):
        with open(f) as fh:
            data = json.load(fh)
            if data["id"].startswith(session_id):
                f.unlink()
                return True
    return False


def get_messages(session_id: str) -> list:
    data = get_session(session_id)
    if data:
        return data.get("messages", [])
    return []
