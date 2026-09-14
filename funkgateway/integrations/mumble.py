"""Optional Mumble integration backends.

The local backend uses the Mumble client's small D-Bus API through ``busctl``.
The Ice backend is optional and intended for administrators.  No Ice secret is
persisted by this module; callers pass it only for the operation that needs it.
"""
from __future__ import annotations

import importlib
import shlex
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, unquote


def _import_ice():
    """Import ZeroC Ice, also when FunkGateway runs in an older/isolated venv.

    Ubuntu/Debian install python3-zeroc-ice into /usr/lib/python3/dist-packages.
    FunkGateway normally uses a venv with system-site-packages, but installations
    upgraded from older FunkGateway versions can have an isolated venv.  In that
    case we safely add the distro Python path and retry.
    """
    try:
        import Ice
        return Ice
    except Exception as first_exc:
        candidates = [
            Path("/usr/lib/python3/dist-packages"),
            Path("/usr/local/lib/python3/dist-packages"),
        ]
        for path in candidates:
            if path.is_dir() and str(path) not in sys.path:
                sys.path.insert(0, str(path))
                try:
                    import Ice
                    return Ice
                except Exception:
                    pass
        raise first_exc


class MumbleLocalBackend:
    BUS_NAME = "net.sourceforge.mumble.mumble"
    OBJ = "/"
    IFACE = "net.sourceforge.mumble.Mumble"

    @staticmethod
    def installed() -> bool:
        return shutil.which("mumble") is not None

    @staticmethod
    def running() -> bool:
        try:
            out=subprocess.check_output(["busctl","--user","list"], text=True, stderr=subprocess.DEVNULL, timeout=2)
            return MumbleLocalBackend.BUS_NAME in out
        except Exception:
            return False

    def _call(self, method: str) -> str:
        return subprocess.check_output(
            ["busctl","--user","call",self.BUS_NAME,self.OBJ,self.IFACE,method],
            text=True, stderr=subprocess.STDOUT, timeout=2
        ).strip()

    @staticmethod
    def _tokens(out: str):
        try:
            return shlex.split(out)
        except Exception:
            return out.split()

    def current_url(self) -> str:
        tokens=self._tokens(self._call("getCurrentUrl"))
        return tokens[1] if len(tokens) >= 2 and tokens[0] == "s" else ""

    def current_context(self) -> dict:
        url=self.current_url()
        if not url:
            return {"url":"", "connected":False, "user":"", "server":"", "port":0, "channel":""}
        p=urlparse(url)
        channel=unquote((p.path or "").lstrip("/"))
        return {
            "url": url,
            "connected": bool(p.hostname),
            "user": unquote(p.username or ""),
            "server": p.hostname or "",
            "port": p.port or 64738,
            "channel": channel,
        }

    def talking_users(self) -> list[str]:
        tokens=self._tokens(self._call("getTalkingUsers"))
        if len(tokens) < 2 or tokens[0] != "as":
            return []
        try:
            count=int(tokens[1])
        except Exception:
            count=0
        return tokens[2:2+count]

    def is_muted(self) -> bool:
        tokens=self._tokens(self._call("isSelfMuted"))
        return len(tokens)>=2 and tokens[0]=="b" and tokens[1].lower()=="true"

    def is_deaf(self) -> bool:
        tokens=self._tokens(self._call("isSelfDeaf"))
        return len(tokens)>=2 and tokens[0]=="b" and tokens[1].lower()=="true"

    def transmit_mode(self) -> int | None:
        tokens=self._tokens(self._call("getTransmitMode"))
        try:
            return int(tokens[1]) if len(tokens)>=2 and tokens[0]=="u" else None
        except Exception:
            return None

    def status(self) -> dict:
        if not self.installed():
            return {"installed":False,"running":False,"connected":False}
        if not self.running():
            return {"installed":True,"running":False,"connected":False}
        ctx=self.current_context()
        return {
            "installed":True,
            "running":True,
            **ctx,
            "speakers":self.talking_users(),
            "muted":self.is_muted(),
            "deaf":self.is_deaf(),
            "transmit_mode":self.transmit_mode(),
        }


class MumbleIceBackend:
    """Small compatibility wrapper around a server supplied Murmur.ice file."""

    def __init__(self):
        self.tunnel_proc=None
        self._loaded_slice=None

    @staticmethod
    def ice_python_available() -> bool:
        try:
            _import_ice()
            return True
        except Exception:
            return False

    @staticmethod
    def ice_version() -> str:
        try:
            Ice = _import_ice()
            return Ice.stringVersion()
        except Exception:
            return ""

    @staticmethod
    def ice_slice_dir() -> str:
        try:
            Ice = _import_ice()
            return Ice.getSliceDir() or ""
        except Exception:
            return ""

    @staticmethod
    def port_open(host: str, port: int, timeout=0.5) -> bool:
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                return True
        except Exception:
            return False

    def start_ssh_tunnel(self, ssh_host: str, ssh_port: int, ssh_user: str, ice_port: int):
        # Murmur returns proxies that contain its own endpoint (often 127.0.0.1:PORT).
        # Therefore local and remote Ice ports intentionally match.
        if self.port_open("127.0.0.1", ice_port):
            return "Vorhandener lokaler Ice-Tunnel/Listener wird verwendet."
        if not shutil.which("ssh"):
            raise RuntimeError("SSH-Client ist nicht installiert.")
        target=f"{ssh_user}@{ssh_host}" if ssh_user.strip() else ssh_host
        cmd=[
            "ssh","-p",str(int(ssh_port)),"-N",
            "-L",f"127.0.0.1:{int(ice_port)}:127.0.0.1:{int(ice_port)}",
            "-o","ExitOnForwardFailure=yes",
            "-o","ServerAliveInterval=30",
            "-o","ServerAliveCountMax=3",
            "-o","BatchMode=yes",
            target,
        ]
        self.stop_tunnel()
        self.tunnel_proc=subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        deadline=time.monotonic()+5.0
        while time.monotonic()<deadline:
            if self.port_open("127.0.0.1",ice_port):
                return "SSH-Tunnel gestartet."
            if self.tunnel_proc.poll() is not None:
                err=(self.tunnel_proc.stderr.read() if self.tunnel_proc.stderr else "").strip()
                raise RuntimeError(err or "SSH-Tunnel konnte nicht gestartet werden. SSH-Schlüssel/Agent prüfen.")
            time.sleep(0.15)
        self.stop_tunnel()
        raise RuntimeError("SSH-Tunnel wurde nicht rechtzeitig bereit. SSH-Schlüssel/Agent prüfen.")

    def stop_tunnel(self):
        if self.tunnel_proc and self.tunnel_proc.poll() is None:
            try:
                self.tunnel_proc.terminate()
                self.tunnel_proc.wait(timeout=2)
            except Exception:
                try: self.tunnel_proc.kill()
                except Exception: pass
        self.tunnel_proc=None

    def _load(self, slice_file: str):
        path=Path(slice_file).expanduser()
        if not path.exists():
            raise RuntimeError("Murmur.ice wurde nicht gefunden. Bitte die zum Server passende Datei auswählen.")
        try:
            Ice = _import_ice()
        except Exception as e:
            raise RuntimeError(
                "Python-Ice konnte von FunkGateway nicht geladen werden. "
                "Öffne Integrationen → Mumble und klicke auf "
                "'Mumble-Komponenten installieren / reparieren'. "
                "FunkGateway prüft dort automatisch, ob Ice nur in der eigenen "
                "Python-Umgebung repariert werden muss."
            ) from e
        slice_dir=Ice.getSliceDir() or ""
        if not slice_dir:
            raise RuntimeError("Ice-Slice-Verzeichnis fehlt (Paket zeroc-ice-slice).")
        wanted=str(path.resolve())
        if self._loaded_slice != wanted:
            Ice.loadSlice(f'-I"{slice_dir}" "{wanted}"')
            self._loaded_slice=wanted
        Murmur=importlib.import_module("Murmur")
        return Ice, Murmur

    def _connect(self, host: str, port: int, slice_file: str, read_secret: str, server_id: int=1):
        Ice,Murmur=self._load(slice_file)
        props=Ice.createProperties()
        props.setProperty("Ice.Default.EncodingVersion","1.0")
        init=Ice.InitializationData(); init.properties=props
        comm=Ice.initialize([],init)
        try:
            meta=Murmur.MetaPrx.checkedCast(comm.stringToProxy(f"Meta:tcp -h {host} -p {int(port)}"))
            if not meta:
                raise RuntimeError("Mumble-Ice Meta konnte nicht erreicht werden.")
            ctx={"secret":read_secret}
            servers=meta.getAllServers(ctx)
            server=None
            for s in servers:
                if int(s.id(ctx)) == int(server_id):
                    server=s; break
            if server is None:
                raise RuntimeError(f"Mumble-Server-ID {server_id} wurde nicht gefunden.")
            return comm, server, ctx
        except Exception:
            comm.destroy()
            raise

    def test(self, host: str, port: int, slice_file: str, read_secret: str, server_id: int=1) -> dict:
        comm,server,ctx=self._connect(host,port,slice_file,read_secret,server_id)
        try:
            return {"server_id":server.id(ctx),"running":server.isRunning(ctx),"channels":len(server.getChannels(ctx)),"users":len(server.getUsers(ctx))}
        finally:
            comm.destroy()

    def channels(self, host: str, port: int, slice_file: str, read_secret: str, server_id: int=1):
        comm,server,ctx=self._connect(host,port,slice_file,read_secret,server_id)
        try:
            raw=server.getChannels(ctx)
            return sorted([(int(cid), ch.name, int(ch.parent)) for cid,ch in raw.items()], key=lambda x:x[0])
        finally:
            comm.destroy()

    def gateway_state(self, host: str, port: int, slice_file: str, read_secret: str, gateway_name: str, server_id: int=1):
        comm,server,ctx=self._connect(host,port,slice_file,read_secret,server_id)
        try:
            for session,user in server.getUsers(ctx).items():
                if user.name == gateway_name:
                    return {"session":int(session),"name":user.name,"channel":int(user.channel)}
            raise RuntimeError(f'Mumble-Gateway-Benutzer "{gateway_name}" ist derzeit nicht verbunden.')
        finally:
            comm.destroy()

    def move_gateway(self, host: str, port: int, slice_file: str, read_secret: str, write_secret: str,
                     gateway_name: str, target_channel: int, server_id: int=1):
        comm,server,read_ctx=self._connect(host,port,slice_file,read_secret,server_id)
        try:
            user=None
            for _session,state in server.getUsers(read_ctx).items():
                if state.name == gateway_name:
                    user=state; break
            if user is None:
                raise RuntimeError(f'Mumble-Gateway-Benutzer "{gateway_name}" ist derzeit nicht verbunden.')
            old=int(user.channel)
            user.channel=int(target_channel)
            server.setState(user,{"secret":write_secret})
            return old
        finally:
            comm.destroy()


class MumbleBridgeBackend:
    """Client for the restricted FunkGateway Mumble Bridge.

    Normal gateway operators use only a personal bridge token.  The Murmur Ice
    read/write secrets stay on an administrator-controlled server/management
    host and are never required on the gateway computer.
    """

    @staticmethod
    def _url(base_url: str, path: str) -> str:
        base=(base_url or "").strip().rstrip("/")
        if not base:
            raise RuntimeError("Bitte die Bridge-Adresse eintragen.")
        if not (base.startswith("https://") or base.startswith("http://")):
            raise RuntimeError("Bridge-Adresse muss mit https:// beginnen (für lokale Tests ist http:// möglich).")
        return base + path

    @staticmethod
    def _request(base_url: str, path: str, token: str="", method: str="GET") -> dict:
        import json
        import urllib.request
        import urllib.error
        url=MumbleBridgeBackend._url(base_url,path)
        headers={"Accept":"application/json","User-Agent":"FunkGateway-UI"}
        if token:
            headers["Authorization"]="Bearer " + token.strip()
        req=urllib.request.Request(url, data=(b"" if method=="POST" else None), headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                data=r.read().decode("utf-8","replace")
                return json.loads(data or "{}")
        except urllib.error.HTTPError as e:
            try:
                body=e.read().decode("utf-8","replace")
                msg=json.loads(body).get("error",body)
            except Exception:
                msg=str(e)
            raise RuntimeError(f"Bridge antwortet mit HTTP {e.code}: {msg}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Bridge nicht erreichbar: {e.reason}") from e

    def status(self, base_url: str) -> dict:
        return self._request(base_url,"/api/v1/status")

    def gateway(self, base_url: str, token: str) -> dict:
        if not token.strip():
            raise RuntimeError("Bitte das persönliche Bridge-Token eintragen. Das Ice-Secret gehört hier NICHT hinein.")
        return self._request(base_url,"/api/v1/gateway",token)

    def disturbance(self, base_url: str, token: str) -> dict:
        if not token.strip():
            raise RuntimeError("Bitte das persönliche Bridge-Token eintragen.")
        return self._request(base_url,"/api/v1/gateway/disturbance",token,"POST")

    def return_normal(self, base_url: str, token: str) -> dict:
        if not token.strip():
            raise RuntimeError("Bitte das persönliche Bridge-Token eintragen.")
        return self._request(base_url,"/api/v1/gateway/return",token,"POST")
