import asyncio
import json
import sys
from typing import Optional

try:
    import httpx
    HAVE_HTTPX = True
except ImportError:
    HAVE_HTTPX = False


async def attach_to_server(url: str, session_id: Optional[str] = None, prompt: Optional[str] = None):
    if not HAVE_HTTPX:
        print("httpx is required for attach mode. Install: pip install httpx")
        return

    server_url = url.rstrip("/")
    if not server_url.startswith("http"):
        server_url = f"http://{server_url}"

    print(f"  Attaching to {server_url}...")

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.get(f"{server_url}/health")
            if r.status_code != 200:
                print(f"  Server at {server_url} is not responding")
                return
            print(f"  Connected to {server_url}")
        except Exception as e:
            print(f"  Cannot connect to {server_url}: {e}")
            return

        if prompt:
            payload = {"prompt": prompt}
            if session_id:
                payload["session_id"] = session_id
            try:
                r = await client.post(f"{server_url}/api/run", json=payload, timeout=300)
                if r.status_code == 200:
                    result = r.json()
                    print(f"\n  Result: {result.get('result', 'ok')}")
                else:
                    print(f"  Error: {r.text}")
            except Exception as e:
                print(f"  Request failed: {e}")
            return

        print("\n  Interactive attach mode (type 'exit' to quit)")
        while True:
            try:
                user_input = input("\n  Enter prompt: ")
            except (EOFError, KeyboardInterrupt):
                break

            if user_input.lower() in ("exit", "quit", "q"):
                break
            if not user_input.strip():
                continue

            payload = {"prompt": user_input}
            if session_id:
                payload["session_id"] = session_id

            try:
                r = await client.post(f"{server_url}/api/run", json=payload, timeout=600)
                if r.status_code == 200:
                    result = r.json()
                    output = result.get("result", result)
                    print(f"\n  Agent: {str(output)[:500]}")
                else:
                    print(f"  Error: {r.text}")
            except Exception as e:
                print(f"  Request failed: {e}")
