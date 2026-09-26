"""Small TeamSpeak 3 ClientQuery integration.

Designed for the classic TeamSpeak 3 desktop client with the ClientQuery
plugin enabled (normally 127.0.0.1:25639).

The module intentionally has no dependency on the FunkGateway audio core.
Failures here must never interrupt PTT/audio operation.
"""
from __future__ import annotations

import socket
import time
from pathlib import Path


def ts_unescape(value: str) -> str:
    """Decode the most common TeamSpeak query string escapes."""
    # Backslash must be handled last.
    replacements = {
        r"\s": " ",
        r"\p": "|",
        r"\/": "/",
        r"\n": "\n",
        r"\r": "\r",
        r"\t": "\t",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return value.replace(r"\\", "\\")


def ts_escape(value: str) -> str:
    """Escape text for one TeamSpeak query parameter."""
    return (
        value.replace("\\", r"\\")
        .replace(" ", r"\s")
        .replace("|", r"\p")
        .replace("/", r"\/")
    )


def parse_record(record: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for token in record.strip().split():
        if "=" in token:
            key, value = token.split("=", 1)
            result[key] = ts_unescape(value)
    return result


def read_default_api_key() -> str:
    """Read the API key written by the TeamSpeak ClientQuery plugin if present."""
    candidates = [
        Path.home() / ".ts3client" / "clientquery.ini",
        Path.home() / ".config" / "ts3client" / "clientquery.ini",
    ]
    for path in candidates:
        try:
            if not path.exists():
                continue
            for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip().lower() in {"api_key", "apikey"}:
                    return value.strip()
        except Exception:
            pass
    return ""


class TeamSpeakClientQuery:
    """Persistent lightweight connection to the local TS3 ClientQuery plugin.

    0.5.6.6 adds robust server-connection-handler validation/recovery on top of the real TS3 3.6.2 byte stream:
    greeting lines terminated by LF/CR, then immediate ``error id=...`` replies.
    """

    def __init__(self, host="127.0.0.1", port=25639, apikey="", timeout=2.0):
        self.host = host
        self.port = int(port)
        self.apikey = apikey
        self.timeout = float(timeout)
        self.sock: socket.socket | None = None
        self._recv_buffer = b""
        self.connected = False
        self.last_error = ""
        self.schandlerid: int | None = None
        self.clid: int | None = None

    def configure(self, host: str, port: int, apikey: str):
        host = host.strip() or "127.0.0.1"
        port = int(port)
        apikey = apikey.strip()
        if (host, port, apikey) != (self.host, self.port, self.apikey):
            self.close()
            self.host, self.port, self.apikey = host, port, apikey

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        self.sock = None
        self._recv_buffer = b""
        self.connected = False
        self.schandlerid = None
        self.clid = None

    def _readline(self) -> str:
        """Read one ClientQuery line directly from the socket.

        Do not wrap the socket in ``makefile()`` here.  Python buffered socket
        file objects can become unusable after a read timeout ("cannot read
        from timed out object").  ClientQuery is line based, so a tiny local
        receive buffer is both simpler and robust after timeouts.
        """
        if not self.sock:
            raise RuntimeError("ClientQuery ist nicht verbunden")
        while b"\n" not in self._recv_buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("TeamSpeak hat die ClientQuery-Verbindung geschlossen")
            self._recv_buffer += chunk
        raw, self._recv_buffer = self._recv_buffer.split(b"\n", 1)
        return raw.strip(b"\r").decode("utf-8", errors="replace")

    def _drain_greeting(self):
        """Consume the initial ClientQuery greeting without poisoning reads.

        Different TS3/ClientQuery versions emit a slightly different number of
        greeting lines.  We consume complete lines for a short bounded window;
        a timeout simply means that the greeting is finished.
        """
        if not self.sock:
            return
        original_timeout = self.sock.gettimeout()
        deadline = time.monotonic() + max(0.35, min(self.timeout, 1.0))
        try:
            while time.monotonic() < deadline:
                remaining = max(0.05, deadline - time.monotonic())
                self.sock.settimeout(remaining)
                try:
                    line = self._readline()
                except socket.timeout:
                    break
                if line.startswith("selected schandlerid="):
                    break
        finally:
            self.sock.settimeout(original_timeout)


    def _read_greeting_exact(self) -> int | None:
        """Read the real TS3 ClientQuery greeting through selected schandlerid.

        Verified on TS3 Client 3.6.2:
        ``TS3 Client`` -> welcome text -> ``selected schandlerid=1``.
        The handler announced here is remembered, but is validated again after
        AUTH because TeamSpeak can reconnect/change tabs while ClientQuery is alive.
        """
        if not self.sock:
            raise RuntimeError("ClientQuery ist nicht verbunden")
        deadline = time.monotonic() + max(2.0, self.timeout)
        seen = []
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            self.sock.settimeout(remaining)
            try:
                line = self._readline()
            except socket.timeout as exc:
                raise RuntimeError(
                    "TeamSpeak ClientQuery Begrüßung unvollständig "
                    f"(gesehen: {seen[-2:]})"
                ) from exc
            if line:
                seen.append(line)
            if line.startswith("selected schandlerid="):
                self.sock.settimeout(self.timeout)
                try:
                    return int(line.split("=", 1)[1].strip())
                except Exception:
                    return None
        raise RuntimeError("TeamSpeak ClientQuery Begrüßung ohne selected schandlerid")

    @staticmethod
    def _is_invalid_handler_error(err_id: int, err_msg: str) -> bool:
        msg=(err_msg or "").replace(r"\s", " ").lower()
        return "invalid server connection handler id" in msg

    @staticmethod
    def _first_int(lines, key):
        for line in lines:
            for record in line.split("|"):
                info=parse_record(record)
                try:
                    if key in info:
                        return int(info[key])
                except (TypeError, ValueError):
                    pass
        return None

    @staticmethod
    def _all_ints(lines, key):
        values=[]
        for line in lines:
            for record in line.split("|"):
                info=parse_record(record)
                try:
                    if key in info:
                        value=int(info[key])
                        if value not in values:
                            values.append(value)
                except (TypeError, ValueError):
                    pass
        return values

    def _ensure_valid_handler(self):
        """Validate the currently selected TS3 server connection handler.

        Normal path: use the already selected handler and do not send ``use``.
        Recovery path: if TeamSpeak reports no/invalid current handler, list the
        available handlers and select one explicitly with ``use schandlerid=N``.
        """
        lines, err_id, err_msg=self._command_raw("currentschandlerid")
        current=self._first_int(lines, "schandlerid") if err_id == 0 else None

        list_lines, list_err, list_msg=self._command_raw("serverconnectionhandlerlist")
        if list_err != 0:
            raise RuntimeError(
                "TeamSpeak ServerConnectionHandler-Liste konnte nicht gelesen werden: "
                f"{list_msg or list_err}"
            )
        available=self._all_ints(list_lines, "schandlerid")

        if current is not None and current in available:
            self.schandlerid=current
            return current

        # Prefer the handler announced by the greeting when it is still valid,
        # otherwise select the first currently available handler.
        wanted=self.schandlerid if self.schandlerid in available else (available[0] if available else None)
        if wanted is None:
            raise RuntimeError("TeamSpeak hat derzeit keinen gültigen ServerConnectionHandler")

        _, use_err, use_msg=self._command_raw(f"use schandlerid={wanted}")
        if use_err != 0:
            raise RuntimeError(
                f"TeamSpeak ServerConnectionHandler {wanted} konnte nicht ausgewählt werden: "
                f"{use_msg or use_err}"
            )

        verify_lines, verify_err, verify_msg=self._command_raw("currentschandlerid")
        verified=self._first_int(verify_lines, "schandlerid") if verify_err == 0 else None
        if verified != wanted:
            raise RuntimeError(
                f"TeamSpeak ServerConnectionHandler konnte nicht verifiziert werden "
                f"(gewünscht {wanted}, aktuell {verified}, Fehler {verify_msg or verify_err})"
            )
        self.schandlerid=verified
        return verified

    def _connect(self):
        if self.connected and self.sock:
            return
        self.close()
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        self._recv_buffer = b""

        # ClientQuery sends a deterministic greeting.  The real TS3 3.6.2
        # field test ends it with ``selected schandlerid=...``.  Consume exactly
        # through that line before sending AUTH.
        self.schandlerid = self._read_greeting_exact()

        if self.apikey:
            try:
                # IMPORTANT: send the API key byte-for-byte as stored in
                # clientquery.ini.  It is an opaque credential, not a normal
                # TeamSpeak query text parameter; escaping '/' changed real
                # API keys and could prevent authentication.
                _, err_id, err_msg = self._command_raw(f"auth apikey={self.apikey}")
            except Exception as exc:
                raise RuntimeError(f"ClientQuery-Timeout bei AUTH: {exc}") from exc
            if err_id != 0:
                raise RuntimeError(f"ClientQuery-Anmeldung fehlgeschlagen: {err_msg or err_id}")

        # Validate, but do not unnecessarily re-select, the active handler.
        # This keeps the normal TS3 3.6.2 path exactly as observed in field tests
        # while allowing recovery after a TeamSpeak reconnect/tab change.
        self._ensure_valid_handler()
        self.connected = True
        self.last_error = ""

    def _command_raw(self, command: str):
        if not self.sock:
            raise RuntimeError("ClientQuery ist nicht verbunden")
        self.sock.sendall((command + "\n").encode("utf-8"))
        data_lines: list[str] = []
        while True:
            try:
                line = self._readline()
            except socket.timeout as exc:
                raise RuntimeError(
                    f"TeamSpeak ClientQuery antwortet auf '{command}' nicht innerhalb von {self.timeout:.2f} s"
                ) from exc
            if line.startswith("error "):
                err = parse_record(line)
                try:
                    err_id = int(err.get("id", "-1"))
                except ValueError:
                    err_id = -1
                return data_lines, err_id, err.get("msg", "")
            if line:
                data_lines.append(line)

    def command(self, command: str):
        try:
            self._connect()
            result=self._command_raw(command)
            lines, err_id, err_msg=result
            if self._is_invalid_handler_error(err_id, err_msg):
                # TeamSpeak may keep ClientQuery alive while its server handler
                # was recreated. Reconnect, re-discover the handler and retry once.
                self.close()
                self._connect()
                result=self._command_raw(command)
            return result
        except Exception as exc:
            self.last_error = str(exc)
            self.close()
            raise

    def test(self) -> str:
        # Validate handler first so connection-test errors identify the context.
        self._connect()
        self._ensure_valid_handler()
        lines, err_id, err_msg = self._command_raw("whoami")
        if self._is_invalid_handler_error(err_id, err_msg):
            self.close()
            self._connect()
            lines, err_id, err_msg = self._command_raw("whoami")
        if err_id != 0:
            raise RuntimeError(err_msg or f"ClientQuery Fehler {err_id}")
        self.clid=self._first_int(lines, "clid")
        cid=self._first_int(lines, "cid")
        return f"schandlerid={self.schandlerid} clid={self.clid} cid={cid}"

    def speakers(self) -> list[str]:
        """Return all currently talking voice-client nicknames visible to TS3.

        Also remember whether the local ClientQuery client itself is talking.
        ``whoami()`` should have been called beforehand so ``self.clid`` is known.
        """
        lines, err_id, err_msg = self.command("clientlist -voice")
        if err_id != 0:
            raise RuntimeError(err_msg or f"clientlist Fehler {err_id}")
        if not lines:
            return []
        # Client lists use | as record separator. Multiple data lines are rare
        # but joining them keeps the parser resilient.
        raw = "|".join(lines)
        speakers: list[str] = []
        self._self_talking=False
        for record in raw.split("|"):
            info = parse_record(record)
            if info.get("client_type", "0") != "0":
                continue
            talking=info.get("client_flag_talking") == "1"
            try:
                record_clid=int(info.get("clid","0") or 0)
            except (TypeError,ValueError):
                record_clid=0
            if talking and self.clid and record_clid == self.clid:
                self._self_talking=True
            if talking:
                nickname = info.get("client_nickname", "").strip()
                if nickname:
                    speakers.append(nickname)
        return speakers

    def self_talking(self) -> bool:
        """Return the local TS client's talking state from the last voice list."""
        return bool(getattr(self,"_self_talking",False))


    def whoami(self) -> dict[str, str]:
        """Return the local TeamSpeak client's current IDs."""
        lines, err_id, err_msg = self.command("whoami")
        if err_id != 0:
            raise RuntimeError(err_msg or f"whoami Fehler {err_id}")
        info = {}
        for line in lines:
            info.update(parse_record(line))
        try:
            self.clid = int(info.get("clid", "0")) or None
        except (TypeError, ValueError):
            self.clid = None
        return info

    def current_channel(self) -> tuple[int | None, str]:
        """Return ``(cid, channel_name)`` for the gateway client.

        TS3 ClientQuery 3.6.2 does not implement ``channelinfo``.  The real
        client accepts ``channelvariable cid=<id> channel_name`` instead.
        """
        me = self.whoami()
        try:
            cid = int(me.get("cid", "0"))
        except (TypeError, ValueError):
            cid = 0
        if cid <= 0:
            return None, "—"
        lines, err_id, err_msg = self.command(f"channelvariable cid={cid} channel_name")
        if err_id != 0:
            # Channel-name lookup is optional.  Keep the TeamSpeak core alive
            # even when this comfort function is unavailable.
            return cid, f"Channel {cid}"
        info = {}
        for line in lines:
            info.update(parse_record(line))
        return cid, info.get("channel_name", f"Channel {cid}")

    def server_identity(self) -> tuple[str, str]:
        """Return a best-effort stable server key and readable server name.

        Prefer the TeamSpeak server UID.  If this optional ClientQuery command
        is unavailable, fall back to the current handler so protection logic
        never breaks the normal gateway operation.
        """
        try:
            lines, err_id, err_msg = self.command(
                "servervariable virtualserver_unique_identifier virtualserver_name"
            )
            if err_id == 0:
                info = {}
                for line in lines:
                    info.update(parse_record(line))
                uid = info.get("virtualserver_unique_identifier", "").strip()
                name = info.get("virtualserver_name", "").strip() or "TeamSpeak-Server"
                if uid:
                    return f"uid:{uid}", name
        except Exception:
            pass
        handler = self.schandlerid or 0
        return f"handler:{handler}", f"TeamSpeak-Server (Handler {handler})"

    def channels(self) -> list[tuple[int, str]]:
        """Return channels visible to the current TeamSpeak client."""
        lines, err_id, err_msg = self.command("channellist")
        if err_id != 0:
            raise RuntimeError(err_msg or f"channellist Fehler {err_id}")
        raw = "|".join(lines)
        result: list[tuple[int, str]] = []
        for record in raw.split("|"):
            info = parse_record(record)
            try:
                cid = int(info.get("cid", "0"))
            except (TypeError, ValueError):
                continue
            if cid <= 0:
                continue
            name = info.get("channel_name", f"Channel {cid}").strip() or f"Channel {cid}"
            result.append((cid, name))
        return result

    def move_self(self, target_cid: int):
        """Move only the local gateway client to ``target_cid``."""
        me = self.whoami()
        try:
            clid = int(me.get("clid", "0"))
        except (TypeError, ValueError):
            clid = 0
        if clid <= 0:
            raise RuntimeError("Eigene TeamSpeak Client-ID konnte nicht ermittelt werden")
        target_cid = int(target_cid)
        lines, err_id, err_msg = self.command(f"clientmove clid={clid} cid={target_cid}")
        if err_id != 0:
            raise RuntimeError(err_msg or f"clientmove Fehler {err_id}")
        return True

    def set_input_muted(self, enabled: bool):
        """Mute/unmute the local TeamSpeak gateway client's microphone."""
        value="1" if enabled else "0"
        lines,err_id,err_msg=self.command(f"clientupdate client_input_muted={value}")
        if err_id != 0:
            raise RuntimeError(err_msg or f"TeamSpeak Mikrofon-Mute Fehler {err_id}")
        return True

    def set_output_muted(self, enabled: bool):
        """Deafen/undeafen the local TeamSpeak gateway client's playback."""
        value="1" if enabled else "0"
        lines,err_id,err_msg=self.command(f"clientupdate client_output_muted={value}")
        if err_id != 0:
            raise RuntimeError(err_msg or f"TeamSpeak Ausgabe-Mute Fehler {err_id}")
        return True

    def set_channel_commander(self, enabled: bool):
        value = "1" if enabled else "0"
        # ClientQuery / server versions have historically exposed both spellings.
        # Try the canonical client property first and the shorter spelling as a
        # compatibility fallback.
        attempts = [
            f"clientupdate client_is_channel_commander={value}",
            f"clientupdate is_channel_commander={value}",
        ]
        last = None
        for command in attempts:
            lines, err_id, err_msg = self.command(command)
            if err_id == 0:
                return True
            last = RuntimeError(err_msg or f"ClientQuery Fehler {err_id}")
        raise last or RuntimeError("Channel Commander konnte nicht geändert werden")

    def clients(self, current_channel_only: bool = False) -> list[dict[str, object]]:
        """Return normal voice clients visible to the current TeamSpeak user."""
        me=self.whoami()
        try:
            own_cid=int(me.get("cid","0") or 0)
        except (TypeError,ValueError):
            own_cid=0

        lines,err_id,err_msg=self.command("clientlist -uid -voice")
        if err_id != 0:
            raise RuntimeError(err_msg or f"clientlist Fehler {err_id}")

        result=[]
        for record in "|".join(lines).split("|"):
            info=parse_record(record)
            if info.get("client_type","0") != "0":
                continue
            try:
                clid=int(info.get("clid","0") or 0)
                cid=int(info.get("cid","0") or 0)
            except (TypeError,ValueError):
                continue
            if clid <= 0:
                continue
            if current_channel_only and own_cid > 0 and cid != own_cid:
                continue
            result.append({
                "clid":clid,
                "cid":cid,
                "nickname":info.get("client_nickname",f"Client {clid}").strip() or f"Client {clid}",
                "uid":info.get("client_unique_identifier","").strip(),
                "talking":info.get("client_flag_talking") == "1",
                "is_self":bool(self.clid and clid == self.clid),
            })
        result.sort(key=lambda x: (not bool(x["is_self"]), str(x["nickname"]).lower()))
        return result

    def poke_client(self, clid: int, message: str):
        clid=int(clid)
        message=(message or "").strip()
        if clid <= 0:
            raise ValueError("Ungültige Client-ID")
        if not message:
            raise ValueError("Poke-Nachricht ist leer")
        _,err_id,err_msg=self.command(f"clientpoke clid={clid} msg={ts_escape(message)}")
        if err_id != 0:
            raise RuntimeError(err_msg or f"clientpoke Fehler {err_id}")
        return True

    def move_client(self, clid: int, target_cid: int):
        clid=int(clid); target_cid=int(target_cid)
        if clid <= 0 or target_cid <= 0:
            raise ValueError("Ungültige Client- oder Channel-ID")
        _,err_id,err_msg=self.command(f"clientmove clid={clid} cid={target_cid}")
        if err_id != 0:
            raise RuntimeError(err_msg or f"clientmove Fehler {err_id}")
        return True

    def kick_client(self, clid: int, from_server: bool = False, reason: str = ""):
        clid=int(clid)
        if clid <= 0:
            raise ValueError("Ungültige Client-ID")
        reason_id=5 if from_server else 4
        command=f"clientkick clid={clid} reasonid={reason_id}"
        reason=(reason or "").strip()
        if reason:
            command += f" reasonmsg={ts_escape(reason)}"
        _,err_id,err_msg=self.command(command)
        if err_id != 0:
            raise RuntimeError(err_msg or f"clientkick Fehler {err_id}")
        return True

