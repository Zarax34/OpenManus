import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from cli.session import get_session, SESSION_DIR


def export_session(session_id: str, output_path: Optional[str] = None) -> Optional[str]:
    data = get_session(session_id)
    if not data:
        return None

    export = {
        "exported_at": datetime.now().isoformat(),
        "source": "openmanus",
        "version": "0.2.0",
        "session": {
            "id": data["id"],
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "messages": data.get("messages", []),
        },
    }

    if output_path:
        path = Path(output_path)
    else:
        exports_dir = SESSION_DIR.parent / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        path = exports_dir / f"session_{data['id'][:8]}.json"

    with open(path, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)

    return str(path)


def import_session(file_path: str) -> Optional[dict]:
    path = Path(file_path)
    if not path.exists():
        return None

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, Exception):
        return None

    session_data = data.get("session", data)
    session_id = session_data.get("id")
    if not session_id:
        import uuid
        session_id = str(uuid.uuid4())
        session_data["id"] = session_id

    session_data.setdefault("created_at", datetime.now().isoformat())
    session_data["updated_at"] = datetime.now().isoformat()
    session_data.setdefault("messages", [])
    session_data["message_count"] = len(session_data["messages"])

    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    dest = SESSION_DIR / f"{session_id}.json"
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(session_data, f, indent=2, ensure_ascii=False)

    return {
        "id": session_id,
        "path": str(dest),
        "messages": len(session_data["messages"]),
    }
