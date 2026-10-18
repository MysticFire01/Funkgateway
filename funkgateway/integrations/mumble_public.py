from __future__ import annotations

import json
import socket
import struct
import time
import urllib.request
import ssl
import shutil
import subprocess
import xml.etree.ElementTree as ET

from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QObject, Signal, QEventLoop, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply


# Official public list used by the Mumble desktop client.
OFFICIAL_PUBLIC_LIST_URL = "https://publist.mumble.info/v1/list?version=1.5.939"

# Fallback only. This endpoint currently returns a much smaller result set.
LEGACY_PUBLIC_LIST_URL = "https://www.mumble.com/serverlist/ajax/list-servers.php"


def _legacy_ping(host: str, port: int, timeout: float = 0.7) -> dict:
    """Legacy Mumble UDP ping used by the desktop client's server browser."""
    result = {
        "ping_ms": None,
        "users": None,
        "max_users": None,
        "bandwidth": None,
        "version": "",
    }
    try:
        infos = socket.getaddrinfo(host, int(port), 0, socket.SOCK_DGRAM)
    except Exception:
        return result

    ident = time.monotonic_ns() & 0xFFFFFFFFFFFFFFFF
    packet = struct.pack(">iQ", 0, ident)

    for family, socktype, proto, _canon, sockaddr in infos:
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(float(timeout))
            started = time.perf_counter()
            sock.sendto(packet, sockaddr)
            data, _addr = sock.recvfrom(1024)
            elapsed = (time.perf_counter() - started) * 1000.0
            if len(data) < 24:
                continue
            major, minor, patch, _sub, returned_ident, users, max_users, bandwidth = struct.unpack(
                ">bbbbQiii", data[:24]
            )
            if returned_ident != ident:
                continue
            result.update({
                "ping_ms": round(elapsed, 1),
                "users": max(0, int(users)),
                "max_users": max(0, int(max_users)),
                "bandwidth": max(0, int(bandwidth)),
                "version": f"{major}.{minor}.{patch}",
            })
            return result
        except Exception:
            continue
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
    return result


def _download_qt(url: str, accept: str, timeout_ms: int = 20000) -> tuple[bytes, dict]:
    """Fetch with QtNetwork, matching the transport stack used by Mumble itself.

    The official publist endpoint currently rejects the urllib/HTTP path on
    some Windows systems with HTTP 501 / Transfer-Encoding errors. QtNetwork
    avoids that incompatibility and is already part of FunkGateway via PySide6.
    """
    manager = QNetworkAccessManager()
    request = QNetworkRequest(QUrl(url))
    # Keep the request intentionally close to Mumble's own WebFetch path.
    # In particular, do not force Connection/Transfer-Encoding related headers.
    request.setRawHeader(b"User-Agent", b"Mumble/1.5.939 FunkGateway-Linux")
    request.setRawHeader(b"Accept", accept.encode("ascii", errors="ignore"))

    reply = manager.get(request)
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)

    timed_out = {"value": False}

    def on_timeout():
        timed_out["value"] = True
        try:
            reply.abort()
        except Exception:
            pass
        loop.quit()

    reply.finished.connect(loop.quit)
    timer.timeout.connect(on_timeout)
    timer.start(int(timeout_ms))
    loop.exec()

    if timer.isActive():
        timer.stop()

    if timed_out["value"]:
        reply.deleteLater()
        raise RuntimeError("Zeitüberschreitung beim Abruf der offiziellen Mumble-Liste")

    status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
    try:
        status = int(status) if status is not None else 0
    except Exception:
        status = 0

    error_code = reply.error()
    error_text = reply.errorString()
    raw = bytes(reply.readAll())

    headers = {}
    try:
        for name in reply.rawHeaderList():
            key = bytes(name).decode("latin1", errors="replace")
            value = bytes(reply.rawHeader(name)).decode("latin1", errors="replace")
            headers[key] = value
    except Exception:
        pass

    reply.deleteLater()

    if error_code != QNetworkReply.NetworkError.NoError:
        raise RuntimeError(
            f"QtNetwork Fehler {int(error_code)}"
            + (f" / HTTP {status}" if status else "")
            + f": {error_text}"
        )
    if status and not (200 <= status < 300):
        raise RuntimeError(f"HTTP {status} beim Abruf der offiziellen Mumble-Liste")
    if not raw:
        raise RuntimeError("Offizielle Mumble-Liste lieferte keine Daten")

    return raw, headers


def _download(url: str, accept: str) -> tuple[bytes, object]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mumble/1.5.939 FunkGateway-Windows",
            "Accept": accept,
            "Accept-Encoding": "identity",
        },
    )
    # Use Linux system CA certificates for TLS verification.
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=20, context=context) as response:
        return response.read(), response.headers


def _download_official_via_curl(url: str) -> tuple[bytes, dict]:
    """Alternate HTTP client where QtNetwork cannot fetch publist.

    Linux usually ships curl. We use HTTP/1.1 because the public
    list service has historically been picky about transfer framing.
    """
    exe = shutil.which("curl")
    if not exe:
        raise RuntimeError("curl nicht gefunden")
    result = subprocess.run(
        [
            exe, "--silent", "--show-error", "--fail",
            "--location", "--http1.1",
            "--connect-timeout", "10", "--max-time", "25",
            "--user-agent", "Mumble/1.5.939 FunkGateway-Windows",
            "--header", "Accept: application/xml,text/xml;q=0.9,*/*;q=0.8",
            url,
        ],
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        err = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"curl Fehler {result.returncode}: {err}")
    if not result.stdout:
        raise RuntimeError("curl lieferte keine Daten")
    return bytes(result.stdout), {}


def _load_official_list() -> list[dict]:
    errors = []
    raw = b""
    try:
        raw, _headers = _download_qt(
            OFFICIAL_PUBLIC_LIST_URL,
            "application/xml,text/xml;q=0.9,*/*;q=0.8",
        )
    except Exception as exc:
        errors.append("QtNetwork: " + str(exc))
        try:
            raw, _headers = _download_official_via_curl(
                OFFICIAL_PUBLIC_LIST_URL
            )
        except Exception as curl_exc:
            errors.append("curl: " + str(curl_exc))
            try:
                raw, _headers = _download(
                    OFFICIAL_PUBLIC_LIST_URL,
                    "application/xml,text/xml;q=0.9,*/*;q=0.8",
                )
            except Exception as urllib_exc:
                errors.append("urllib: " + str(urllib_exc))
                raise RuntimeError(" | ".join(errors))
    root = ET.fromstring(raw)
    servers = []
    for elem in root.iter("server"):
        host = str(elem.attrib.get("ip") or "").strip()
        if not host:
            continue
        try:
            port = int(elem.attrib.get("port") or 64738)
        except Exception:
            port = 64738

        country = str(elem.attrib.get("country") or "Unbekannt").strip() or "Unbekannt"
        country_code = str(elem.attrib.get("country_code") or "").strip().upper()
        servers.append({
            "name": str(elem.attrib.get("name") or host).strip() or host,
            "host": host,
            "port": port,
            "country": country,
            "country_code": country_code,
            "continent_code": str(elem.attrib.get("continent_code") or "").strip().upper(),
            "region": "",
            "provider": "",
            "url": str(elem.attrib.get("url") or "").strip(),
            "ca": str(elem.attrib.get("ca") or "0") == "1",
            "users": None,
            "max_users": None,
            "ping_ms": None,
            "bandwidth": None,
            "version": "",
            "source": "official",
        })
    return servers


def _load_legacy_list() -> list[dict]:
    raw, _headers = _download(LEGACY_PUBLIC_LIST_URL, "application/json")
    payload = json.loads(raw.decode("utf-8", errors="replace"))
    servers = []
    for row in payload.get("results") or []:
        host = str(row.get("HOSTNAME") or row.get("IP") or "").strip()
        if not host:
            continue
        try:
            port = int(row.get("PORT") or 64738)
        except Exception:
            port = 64738
        servers.append({
            "name": str(row.get("NAME") or host).strip() or host,
            "host": host,
            "port": port,
            "country": str(row.get("COUNTRY") or "Unbekannt").strip() or "Unbekannt",
            "country_code": str(row.get("COUNTRY_CODE") or "").strip().upper(),
            "continent_code": "",
            "region": str(row.get("REGION") or "").strip(),
            "provider": str(row.get("PROVIDER") or "").strip(),
            "url": "",
            "ca": False,
            "users": None,
            "max_users": None,
            "ping_ms": None,
            "bandwidth": None,
            "version": "",
            "source": "legacy-fallback",
        })
    return servers


class MumblePublicServerLoader(QObject):
    loaded = Signal(object)
    error = Signal(str)
    progress = Signal(int, int)
    sourceChanged = Signal(str, int)
    sourceDetail = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        try:
            source = "official"
            try:
                servers = _load_official_list()
                if not servers:
                    raise RuntimeError("Offizielle Mumble-Liste war leer")
            except Exception as official_exc:
                # Keep a fallback so the server browser still remains usable if
                # the official service is temporarily unreachable. Preserve the
                # real exception so the UI can explain WHY fallback is active.
                source = "legacy-fallback"
                self.sourceDetail.emit(
                    f"{type(official_exc).__name__}: {official_exc}"
                )
                servers = _load_legacy_list()
                if not servers:
                    raise RuntimeError(
                        "Offizielle Mumble-Liste nicht erreichbar und Fallback leer: "
                        + str(official_exc)
                    )

            # Remove duplicate host/port records while preserving the first
            # official display name/country metadata.
            unique = {}
            for server in servers:
                key = (
                    str(server.get("host") or "").casefold(),
                    int(server.get("port") or 64738),
                )
                if key not in unique:
                    unique[key] = server
            servers = list(unique.values())

            total = len(servers)
            self.sourceChanged.emit(source, total)
            self.progress.emit(0, total)

            # Mumble's lightweight UDP ping exposes current/max users and ping.
            # A moderate worker count keeps the full public list responsive
            # without opening an excessive number of simultaneous sockets.
            with ThreadPoolExecutor(max_workers=32) as pool:
                futures = {
                    pool.submit(_legacy_ping, srv["host"], srv["port"]): index
                    for index, srv in enumerate(servers)
                }
                done = 0
                for future in as_completed(futures):
                    index = futures[future]
                    try:
                        servers[index].update(future.result())
                    except Exception:
                        pass
                    done += 1
                    if done == total or done % 10 == 0:
                        self.progress.emit(done, total)

            self.loaded.emit(servers)
        except Exception as exc:
            self.error.emit(str(exc))
