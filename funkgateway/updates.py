"""Safe GitHub-release update helper for FunkGateway UI."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO_OWNER = "MysticFire01"
REPO_NAME = "Funkgateway"
API_LATEST = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"


def _version_tuple(value: str):
    value = (value or "").strip().lstrip("vV")
    nums = re.findall(r"\d+", value)
    return tuple(int(x) for x in nums[:4]) or (0,)


def is_newer(remote: str, local: str) -> bool:
    a = _version_tuple(remote)
    b = _version_tuple(local)
    n = max(len(a), len(b))
    return a + (0,) * (n-len(a)) > b + (0,) * (n-len(b))


def fetch_latest_release(timeout=8):
    req = urllib.request.Request(
        API_LATEST,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "FunkGateway-UI-Updater",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _os_release():
    data = {}
    p = Path("/etc/os-release")
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k] = v.strip().strip('"')
    return data


def desired_asset_tokens():
    osr = _os_release()
    os_id = osr.get("ID", "").lower()
    ver = osr.get("VERSION_ID", "")
    machine = platform.machine().lower()
    arm64 = machine in ("aarch64", "arm64")

    if arm64:
        return ["RaspberryPi-arm64", "Generic-Linux-arm64", "Generic-Linux"]

    if os_id == "ubuntu" and ver in ("22.04", "24.04", "26.04"):
        return [f"Ubuntu{ver}-LTS", "Generic-Linux"]
    if os_id == "debian" and ver in ("12", "13"):
        return [f"Debian{ver}", "Generic-Linux"]
    return ["Generic-Linux"]


def choose_asset(release):
    assets = release.get("assets") or []
    zip_assets = [a for a in assets if str(a.get("name", "")).lower().endswith(".zip")]
    for token in desired_asset_tokens():
        for asset in zip_assets:
            if token.lower() in asset.get("name", "").lower():
                return asset
    return None


def _download_bytes(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "FunkGateway-UI-Updater"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def _expected_sha256(release, asset):
    digest = str(asset.get("digest") or "")
    if digest.lower().startswith("sha256:"):
        return digest.split(":", 1)[1].strip().lower()

    wanted = asset.get("name", "") + ".sha256"
    for a in release.get("assets") or []:
        if a.get("name") == wanted:
            txt = _download_bytes(a["browser_download_url"]).decode("utf-8", "replace")
            m = re.search(r"\b([0-9a-fA-F]{64})\b", txt)
            if m:
                return m.group(1).lower()

    for a in release.get("assets") or []:
        if "ALL-SHA256" in a.get("name", "").upper():
            txt = _download_bytes(a["browser_download_url"]).decode("utf-8", "replace")
            for line in txt.splitlines():
                if asset.get("name", "") in line:
                    m = re.search(r"\b([0-9a-fA-F]{64})\b", line)
                    if m:
                        return m.group(1).lower()
    return None



def _make_update_scripts_executable(target: Path):
    """Restore executable bits that can be lost by ZIP extraction."""
    target = Path(target)
    changed = []
    candidates = []

    # All shell scripts in the package should be directly executable.
    candidates.extend(target.rglob("*.sh"))

    # Keep this explicit for future launchers without a .sh suffix.
    for name in ("start.sh", "install.sh", "install-desktop.sh", "repair-venv.sh"):
        p = target / name
        if p.exists():
            candidates.append(p)

    seen = set()
    for p in candidates:
        try:
            p = p.resolve()
        except Exception:
            continue
        if p in seen or not p.is_file():
            continue
        seen.add(p)
        mode = p.stat().st_mode
        # u/g/o +x, keep existing read/write bits.
        new_mode = mode | 0o111
        if new_mode != mode:
            p.chmod(new_mode)
            changed.append(str(p))
    return changed


def find_preferred_installer(target: Path):
    """Return the distro-specific installer in an extracted release."""
    target = Path(target)
    osr = _os_release()
    os_id = osr.get("ID", "").lower()
    ver = osr.get("VERSION_ID", "")

    names = []
    if os_id == "ubuntu" and ver:
        names.append(f"install-ubuntu-{ver}.sh")
    if os_id == "debian" and ver:
        names.append(f"install-debian-{ver}.sh")

    names.extend(("install-linux.sh", "install.sh"))

    for name in names:
        p = target / name
        if p.is_file():
            return p
    return None


def _terminal_command(script_path: Path):
    """Build a command for a commonly available graphical terminal."""
    script = str(Path(script_path))
    terminals = (
        ("gnome-terminal", ["gnome-terminal", "--", "bash", script]),
        ("kgx", ["kgx", "--", "bash", script]),
        ("konsole", ["konsole", "-e", "bash", script]),
        ("xfce4-terminal", ["xfce4-terminal", "--command", f"bash {shlex.quote(script)}"]),
        ("mate-terminal", ["mate-terminal", "--", "bash", script]),
        ("x-terminal-emulator", ["x-terminal-emulator", "-e", "bash", script]),
        ("xterm", ["xterm", "-e", "bash", script]),
    )
    for binary, cmd in terminals:
        if shutil.which(binary):
            return cmd
    return None


def create_update_install_launcher(target: Path, install_desktop=True):
    """Create a small local launcher that runs installer + optional desktop shortcut."""
    target = Path(target)
    installer = find_preferred_installer(target)
    if not installer:
        raise RuntimeError(
            "Im neuen Versionsordner wurde kein passendes Installationsskript gefunden."
        )

    launcher = target / ".funkgateway-update-install.sh"
    desktop_cmd = "./install-desktop.sh" if install_desktop else ":"

    content = f"""#!/usr/bin/env bash
set -u
cd {shlex.quote(str(target))}

echo "============================================================"
echo " FunkGateway UI – Update-Installation"
echo "============================================================"
echo
echo "Neue Version:"
echo "  {str(target)}"
echo
echo "Installer:"
echo "  ./{installer.name}"
echo
echo "Falls erforderlich, fragt sudo jetzt nach dem Passwort."
echo

if ./{shlex.quote(installer.name)}; then
    echo
    echo "FunkGateway-Installation erfolgreich."
else
    rc=$?
    echo
    echo "FEHLER: Installationsskript wurde mit Exit-Code $rc beendet."
    echo
    read -r -p "Enter zum Schliessen ..." _
    exit "$rc"
fi

if {desktop_cmd}; then
    {"echo 'Schnellstarter wurde auf die neue Version aktualisiert.'" if install_desktop else "echo 'Schnellstarter wurde nicht geändert.'"}
else
    rc=$?
    echo
    echo "WARNUNG: Schnellstarter konnte nicht aktualisiert werden (Exit-Code $rc)."
fi

echo
echo "Update-Installation abgeschlossen."
echo "Die bisherige Version wurde nicht gelöscht."
echo
read -r -p "Enter zum Schliessen ..." _
"""
    launcher.write_text(content, encoding="utf-8")
    launcher.chmod(0o755)
    return launcher, installer


def launch_update_installer(target: Path, install_desktop=True):
    """Open the prepared installer in a terminal so sudo can prompt normally."""
    target = Path(target)
    _make_update_scripts_executable(target)
    launcher, installer = create_update_install_launcher(
        target, install_desktop=install_desktop
    )
    cmd = _terminal_command(launcher)
    if not cmd:
        raise RuntimeError(
            "Kein unterstütztes grafisches Terminal gefunden. "
            f"Bitte manuell ausführen: cd {target} && ./{installer.name}"
        )
    subprocess.Popen(cmd, start_new_session=True)
    return {
        "launcher": str(launcher),
        "installer": str(installer),
        "terminal_command": cmd[0],
        "desktop": bool(install_desktop),
    }

def download_and_prepare(release, asset, install_parent: Path):
    cache = Path.home() / ".cache" / "funkgateway-ui" / "updates"
    cache.mkdir(parents=True, exist_ok=True)
    zip_path = cache / asset["name"]

    data = _download_bytes(asset["browser_download_url"], timeout=60)
    zip_path.write_bytes(data)

    actual = hashlib.sha256(data).hexdigest().lower()
    expected = _expected_sha256(release, asset)
    if not expected:
        raise RuntimeError(
            "Für das Release wurde keine SHA256-Prüfsumme gefunden. "
            "Das Update wird aus Sicherheitsgründen nicht vorbereitet."
        )
    if actual != expected:
        raise RuntimeError(
            f"SHA256-Prüfung fehlgeschlagen.\nErwartet: {expected}\nErhalten: {actual}"
        )

    with zipfile.ZipFile(zip_path) as z:
        bad = z.testzip()
        if bad:
            raise RuntimeError(f"ZIP-Prüfung fehlgeschlagen bei: {bad}")
        top_names = [n.split("/", 1)[0] for n in z.namelist() if n and not n.startswith("/")]
        top = top_names[0] if top_names and all(x == top_names[0] for x in top_names) else None

        # Path-traversal guard.
        for member in z.infolist():
            rp = Path(member.filename)
            if rp.is_absolute() or ".." in rp.parts:
                raise RuntimeError("Unsicherer Pfad im Update-ZIP erkannt.")

        target_root = Path(install_parent)
        try:
            target_root.mkdir(parents=True, exist_ok=True)
            test = target_root / ".funkgateway-update-write-test"
            test.write_text("ok", encoding="utf-8")
            test.unlink()
        except Exception:
            target_root = cache / "prepared"
            target_root.mkdir(parents=True, exist_ok=True)

        if top:
            target = target_root / top
            if target.exists():
                raise RuntimeError(f"Zielordner existiert bereits: {target}")
        else:
            tag = str(release.get("tag_name") or "update").lstrip("v")
            target = target_root / f"FunkGateway-UI-{tag}"
            if target.exists():
                raise RuntimeError(f"Zielordner existiert bereits: {target}")

        tmp = Path(tempfile.mkdtemp(prefix="funkgateway-update-", dir=str(cache)))
        try:
            z.extractall(tmp)
            extracted = tmp / top if top else tmp
            if top:
                shutil.move(str(extracted), str(target))
            else:
                target.mkdir(parents=True, exist_ok=False)
                for child in list(tmp.iterdir()):
                    shutil.move(str(child), str(target / child.name))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    executable_files = _make_update_scripts_executable(target)

    return {
        "zip_path": str(zip_path),
        "target": str(target),
        "sha256": actual,
        "asset": asset["name"],
        "executable_files": executable_files,
    }
