"""Readable GitHub release details for update dialogs."""
import re

def readable_changes(release, max_items=8):
    body = str((release or {}).get("body") or "").strip()
    if not body:
        return "Für diese Version wurden keine Neuerungen beschrieben."
    result = []
    for line in body.splitlines():
        line = line.strip().lstrip("-*• ").strip()
        if not line or line.startswith("|") or line.startswith("http"):
            continue
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"[#*_\\x60]", "", line).strip()
        if line:
            result.append("• " + line[:230])
        if len(result) == max_items:
            break
    return "\n".join(result) if result else "Mehr Informationen stehen bei GitHub."
