#!/usr/bin/env python3
"""Read-only Zello connectivity observations. Never transmit audio or remove channels."""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import websocket

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "community/zello_channels.json"
OUTPUT = ROOT / "community/zello_status.json"

def probe(name, token):
    ws = None
    try:
        ws = websocket.create_connection("wss://zello.io/ws", timeout=10)
        ws.settimeout(10)
        ws.send(json.dumps({"command": "logon", "seq": 1,
                            "auth_token": token, "channels": [name],
                            "listen_only": True, "platform_name": "Community Directory Checker"}))
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                data = ws.recv()
            except websocket.WebSocketTimeoutException:
                break
            if not isinstance(data, str):
                continue
            msg = json.loads(data)
            if msg.get("command") == "on_channel_status" and msg.get("channel", "").casefold() == name.casefold():
                if msg.get("status") == "online":
                    return "reachable"
                return "unverified"
            if msg.get("seq") == 1 and msg.get("success") is False:
                return "unverified"
        return "unverified"
    except Exception:
        return "unverified"
    finally:
        if ws is not None:
            try: ws.close()
            except Exception: pass

def main():
    document = json.loads(SOURCE.read_text(encoding="utf-8"))
    channels = document.get("channels", [])
    token = os.environ.get("ZELLO_AUTH_TOKEN", "").strip()
    # No valid credentials: do not claim any channel is offline.
    if not token:
        print("ZELLO_AUTH_TOKEN absent: skipping probes, retaining previous observations.")
        return 0
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    results = []
    seen = set()
    for item in channels[:250]:
        if not isinstance(item, dict) or item.get("platform") != "zello":
            continue
        name = item.get("name", "")
        if not isinstance(name, str) or not name.strip() or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        status = probe(name, token)
        results.append({"name": name, "status": status, "checked_at": now})
        print(f"{name}: {status}")
        time.sleep(1)
    OUTPUT.write_text(json.dumps({"version": 1, "channels": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0

if __name__ == "__main__":
    sys.exit(main())
