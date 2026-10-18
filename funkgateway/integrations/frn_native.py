#!/usr/bin/env python3
"""
FunkGateway – Native FRN Probe Alpha 9

Native FRN test client for FunkGateway UI:
- direct FRN SystemManager explorer (SM)
- selectable DE Alternative / DE Original / RU / all three
- dynamic password request (DP) before server login
- direct server connection without external FRN client
- GSM 06.10 WAV49 RX/TX audio via libgsm
- selectable PortAudio/sounddevice input/output
- manual FRN PTT for TX testing

This is still a test harness, not yet the full FunkGateway integration.
GPL-3.0-or-later
"""
from __future__ import annotations

import ctypes
import ctypes.util
import html
import json
import math
import queue
import re
import socket
import struct
import threading
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, Signal, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox,
    QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QPlainTextEdit, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QScrollArea,
    QTabWidget, QListWidget, QListWidgetItem,
)

try:
    import sounddevice as sd
except Exception:
    sd = None


DEFAULT_PROTOCOL_VERSION = "20261016"
MAX_SERVERS = 5000
MAX_NETS = 128
MAX_CLIENTS_PER_NET = 10000
MAX_LINE = 65536

CLIENT_INDEX_SIZE = 2
FRN_AUDIO_PACKET_SIZE = 325
FRN_AUDIO_SAMPLES = 1600       # 5 x 320 @ 8 kHz = 200 ms
FRN_SAMPLE_RATE = 8000


MANAGERS = {
    "de_alt": {
        "label": "DE – Alternatives FRN System",
        "host": "sysman.freeradionetwork.de",
        "port": 10025,
        "fallback_encoding": "cp1252",
    },
    "de_orig": {
        "label": "DE – Normal / Original FRN",
        "host": "sysman.freeradionetwork.eu",
        "port": 10025,
        "fallback_encoding": "cp1252",
    },
    "ru": {
        "label": "RU – Russisches FRN",
        "host": "sysman.lpd-net.ru",
        "port": 10025,
        "fallback_encoding": "cp1251",
    },
}


def decode_frn(raw: bytes, fallback="cp1252") -> str:
    for enc in ("utf-8", fallback, "cp1252", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("latin1", "replace")


def read_line(fileobj, fallback="cp1252") -> str:
    raw = fileobj.readline(MAX_LINE + 1)
    if not raw:
        raise ConnectionError("Gegenstelle hat die Verbindung beendet.")
    if len(raw) > MAX_LINE:
        raise RuntimeError("FRN-Zeile überschreitet die Schutzgrenze.")
    return decode_frn(raw.rstrip(b"\r\n"), fallback)


def parse_int(text: str, minimum: int, maximum: int, what: str) -> int:
    try:
        value = int(text.strip())
    except Exception as exc:
        raise RuntimeError(f"Ungültige {what}: {text!r}") from exc
    if not (minimum <= value <= maximum):
        raise RuntimeError(f"{what} außerhalb Schutzgrenze: {value}")
    return value


def parse_server_name(text: str):
    m = re.match(r"^\s*(.+?)\s*-\s*Port:\s*(\d{1,5})\s*$", text, re.I)
    if not m:
        return text.strip(), 10024
    port = int(m.group(2))
    return m.group(1).strip(), port


def rms_dbfs(pcm: bytes) -> float:
    if not pcm:
        return -120.0
    count = len(pcm) // 2
    vals = struct.unpack("<" + "h" * count, pcm[:count * 2])
    rms = math.sqrt(sum(v * v for v in vals) / max(1, count))
    return 20.0 * math.log10(max(1.0, rms) / 32768.0)


class GsmWav49:
    """Small ctypes wrapper around Debian's libgsm WAV49 mode."""

    GSM_OPT_WAV49 = 4

    def __init__(self):
        libname = ctypes.util.find_library("gsm") or "libgsm.so.1"
        try:
            self.lib = ctypes.CDLL(libname)
        except OSError as exc:
            raise RuntimeError(
                "libgsm wurde nicht gefunden. Unter Debian: sudo apt install libgsm1"
            ) from exc

        self.lib.gsm_create.restype = ctypes.c_void_p
        self.lib.gsm_destroy.argtypes = [ctypes.c_void_p]
        self.lib.gsm_option.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)
        ]
        self.lib.gsm_option.restype = ctypes.c_int
        self.lib.gsm_encode.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_short),
            ctypes.POINTER(ctypes.c_ubyte),
        ]
        self.lib.gsm_decode.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.POINTER(ctypes.c_short),
        ]
        self.lib.gsm_decode.restype = ctypes.c_int

        self.rx = self.lib.gsm_create()
        self.tx = self.lib.gsm_create()
        if not self.rx or not self.tx:
            raise RuntimeError("libgsm konnte keinen Codec-Zustand anlegen.")

        one = ctypes.c_int(1)
        if self.lib.gsm_option(self.rx, self.GSM_OPT_WAV49, ctypes.byref(one)) == -1:
            raise RuntimeError("libgsm unterstützt GSM WAV49 nicht.")
        one = ctypes.c_int(1)
        if self.lib.gsm_option(self.tx, self.GSM_OPT_WAV49, ctypes.byref(one)) == -1:
            raise RuntimeError("libgsm unterstützt GSM WAV49 nicht.")

        self.rx_lock = threading.Lock()
        self.tx_lock = threading.Lock()

    def close(self):
        for attr in ("rx", "tx"):
            h = getattr(self, attr, None)
            if h:
                try:
                    self.lib.gsm_destroy(h)
                except Exception:
                    pass
                setattr(self, attr, None)

    def decode_packet(self, packet: bytes) -> bytes:
        if len(packet) != FRN_AUDIO_PACKET_SIZE:
            raise ValueError("FRN-Audiopaket muss genau 325 Byte lang sein.")
        src = (ctypes.c_ubyte * len(packet)).from_buffer_copy(packet)
        out = bytearray()
        with self.rx_lock:
            for block in range(5):
                samples = (ctypes.c_short * 320)()
                p1 = ctypes.cast(
                    ctypes.byref(src, block * 65),
                    ctypes.POINTER(ctypes.c_ubyte),
                )
                p2 = ctypes.cast(
                    ctypes.byref(src, block * 65 + 33),
                    ctypes.POINTER(ctypes.c_ubyte),
                )
                o1 = ctypes.cast(samples, ctypes.POINTER(ctypes.c_short))
                o2 = ctypes.cast(
                    ctypes.byref(samples, 160 * ctypes.sizeof(ctypes.c_short)),
                    ctypes.POINTER(ctypes.c_short),
                )
                r1 = self.lib.gsm_decode(self.rx, p1, o1)
                r2 = self.lib.gsm_decode(self.rx, p2, o2)
                if r1 == -1 or r2 == -1:
                    raise RuntimeError("libgsm konnte ein FRN-WAV49-Frame nicht dekodieren.")
                out.extend(
                    ctypes.string_at(ctypes.addressof(samples), ctypes.sizeof(samples))
                )
        return bytes(out)

    def encode_packet(self, pcm: bytes) -> bytes:
        if len(pcm) != FRN_AUDIO_SAMPLES * 2:
            raise ValueError("PCM-Block muss 1600 Samples / 3200 Byte enthalten.")
        samples = (ctypes.c_short * FRN_AUDIO_SAMPLES).from_buffer_copy(pcm)
        dst = (ctypes.c_ubyte * FRN_AUDIO_PACKET_SIZE)()
        with self.tx_lock:
            for block in range(5):
                s1 = ctypes.cast(
                    ctypes.byref(samples, block * 320 * 2),
                    ctypes.POINTER(ctypes.c_short),
                )
                s2 = ctypes.cast(
                    ctypes.byref(samples, (block * 320 + 160) * 2),
                    ctypes.POINTER(ctypes.c_short),
                )
                d1 = ctypes.cast(
                    ctypes.byref(dst, block * 65),
                    ctypes.POINTER(ctypes.c_ubyte),
                )
                # In WAV49 mode libgsm alternates 32/33-byte packed frames.
                # This matches the established SvxLink FRN implementation.
                d2 = ctypes.cast(
                    ctypes.byref(dst, block * 65 + 32),
                    ctypes.POINTER(ctypes.c_ubyte),
                )
                self.lib.gsm_encode(self.tx, s1, d1)
                self.lib.gsm_encode(self.tx, s2, d2)
        return bytes(dst)


class UiSignals(QObject):
    log = Signal(str)
    state = Signal(str)
    connected = Signal(bool)
    clients = Signal(int)
    rx_talker = Signal(str)
    tx_granted = Signal(bool)
    audio_level = Signal(float)
    rx_audio_level = Signal(float)
    participant_list = Signal(object)
    text_message = Signal(object)
    server_room_list = Signal(object)
    error = Signal(str)


class ExplorerSignals(QObject):
    result = Signal(object)
    status = Signal(str)
    error = Signal(str)


class FrnSystemExplorer:
    def __init__(self):
        self.signals = ExplorerSignals()
        self._thread = None
        self.request_kind = None

    def refresh(self, manager_key: str, request_kind: str = "manual"):
        if self._thread and self._thread.is_alive():
            return False
        self.request_kind = request_kind
        self._thread = threading.Thread(
            target=self._worker, args=(manager_key,), daemon=True
        )
        self._thread.start()
        return True

    def _one_manager(self, key: str):
        p = MANAGERS[key]
        sock = socket.create_connection((p["host"], p["port"]), timeout=10)
        sock.settimeout(12)
        f = sock.makefile("rb")
        try:
            sock.sendall(b"SM\r\n")
            server_count = parse_int(
                read_line(f, p["fallback_encoding"]),
                0, MAX_SERVERS, "Serveranzahl"
            )
            rows = []
            for _ in range(server_count):
                server_text = read_line(f, p["fallback_encoding"])
                host, port = parse_server_name(server_text)
                net_count = parse_int(
                    read_line(f, p["fallback_encoding"]),
                    0, MAX_NETS, "Raumanzahl"
                )
                if net_count == 0:
                    rows.append({
                        "manager": key, "host": host, "port": port,
                        "room": "", "clients": 0, "client_info": [],
                    })
                for _n in range(net_count):
                    room = read_line(f, p["fallback_encoding"])
                    client_count = parse_int(
                        read_line(f, p["fallback_encoding"]),
                        0, MAX_CLIENTS_PER_NET, "Clientanzahl"
                    )
                    infos = []
                    # We must consume all client records to stay aligned.
                    for i in range(client_count):
                        line = read_line(f, p["fallback_encoding"])
                        if i < 50:
                            infos.append(line)
                    rows.append({
                        "manager": key, "host": host, "port": port,
                        "room": room, "clients": client_count,
                        "client_info": infos,
                    })
            return rows
        finally:
            try:
                f.close()
            except Exception:
                pass
            sock.close()

    def _worker(self, manager_key: str):
        keys = list(MANAGERS) if manager_key == "all" else [manager_key]
        combined = []
        errors = []
        for key in keys:
            p = MANAGERS[key]
            self.signals.status.emit(f"Lade {p['label']} …")
            try:
                rows = self._one_manager(key)
                combined.extend(rows)
            except Exception as exc:
                errors.append(f"{p['label']}: {exc}")
        self.signals.result.emit(combined)
        if errors:
            self.signals.error.emit("\n".join(errors))
        self.signals.status.emit(
            f"{len(combined)} Server/Raum-Einträge geladen."
            + (f" ({len(errors)} System(e) mit Fehler)" if errors else "")
        )


def get_dynamic_password(manager_key: str, email: str, main_password: str) -> str:
    p = MANAGERS[manager_key]
    sock = socket.create_connection((p["host"], p["port"]), timeout=8)
    sock.settimeout(8)
    f = sock.makefile("rb")
    try:
        req = (
            f"DP:<EA>{html.escape(email)}</EA>"
            f"<PW>{html.escape(main_password)}</PW>\r\n"
        )
        sock.sendall(req.encode("cp1252", "replace"))
        reply = read_line(f, p["fallback_encoding"]).strip()
        if not reply or reply == "-":
            raise RuntimeError("SystemManager lieferte kein dynamisches Passwort.")
        return reply
    finally:
        try:
            f.close()
        except Exception:
            pass
        sock.close()


@dataclass
class FrnConfig:
    manager_key: str
    server: str
    port: int
    email: str
    main_password: str
    callsign_user: str
    protocol_version: str
    client_type: int
    band_channel: str
    description: str
    country: str
    city_part: str
    net: str
    audio_input: Optional[int]
    audio_output: Optional[int]
    audio_enabled: bool
    pulse_audio_input: Optional[str] = None
    allow_main_password_fallback: bool = False


class FrnNativeClient:
    def __init__(self, cfg: FrnConfig):
        self.cfg = cfg
        self.signals = UiSignals()
        self.stop_evt = threading.Event()
        self.sock = None
        self.sock_lock = threading.Lock()
        self.thread = None
        self.buf = bytearray()
        self.state = "DISCONNECTED"

        self.list_kind = None
        self.list_remaining = None
        self.list_items = []
        self.client_list = []
        self.server_room_names = []

        self.codec = None
        self.play_queue = queue.Queue(maxsize=12)
        self.play_thread = None
        self.output_stream = None
        self.input_stream = None
        self.input_proc = None

        self.want_tx = threading.Event()
        self.tx_granted_evt = threading.Event()
        self.tx_thread = None
        self.current_talker_index = 0
        # Local FRN controls; FRN has no Mumble-style server mute/deaf state.
        self.local_mute = False
        self.local_deaf = False

    def _set_state(self, state):
        # Alpha 9: identische Zustände nicht erneut loggen.
        # FRN-Server senden regelmäßig Status-/Idle-Informationen; das soll
        # den Log nicht mehr mit wiederholten "STATE: IDLE" fluten.
        if state == self.state:
            return
        self.state = state
        self.signals.state.emit(state)
        self.signals.log.emit("STATE: " + state)

    def _send(self, data: bytes, label: Optional[str] = None):
        if not self.sock:
            raise ConnectionError("Keine FRN-Verbindung.")
        with self.sock_lock:
            self.sock.sendall(data)
        if label:
            self.signals.log.emit("TX: " + label)

    def send_text_message(self, recipient_id: str, text: str):
        """FRN TM text transport; server delivery remains unconfirmed."""
        if self.stop_evt.is_set() or not self.sock or self.state not in (
            "IDLE", "RX_AUDIO", "RX_LIST", "RX_CLIENT_LIST",
            "RX_EXTENSION_11", "RX_EXTENSION_11_PADDING",
            "TX_AUDIO", "TX_WAITING", "WAIT_TX_INDEX",
        ):
            raise ConnectionError("FRN-Chat: keine angemeldete Verbindung.")
        recipient=str(recipient_id or "").strip()
        message=str(text or "").strip()
        if not recipient or any(x in recipient for x in "<>\r\n") or len(recipient)>128:
            raise ValueError("FRN-Chat: ungültige Empfänger-ID.")
        if not message or len(message)>500 or any(x in message for x in "\r\n\x00"):
            raise ValueError("FRN-Chat: bitte 1 bis 500 Zeichen in einer Zeile eingeben.")
        envelope=f"TM:<ID>{html.escape(recipient)}</ID><MS>{html.escape(message)}</MS>"
        self._send_line(envelope, log=False)

    def _send_line(self, line: str, log=True):
        self._send(
            (line + "\r\n").encode("cp1252", "replace"),
            line if log else None
        )

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_evt.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_evt.set()
        self.want_tx.clear()
        self.tx_granted_evt.clear()
        if self.input_proc:
            try:
                self.input_proc.terminate()
            except Exception:
                pass

        s = self.sock
        if s:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass

        thread = self.thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3.0)
            if thread.is_alive():
                self.signals.log.emit(
                    "WARN: FRN-Thread reagierte beim Stoppen nicht innerhalb von 3 s."
                )

    def set_local_mute(self, enabled: bool):
        self.local_mute = bool(enabled)
        if self.local_mute:
            self.request_tx(False)

    def set_local_deaf(self, enabled: bool):
        self.local_deaf = bool(enabled)

    def request_tx(self, enabled: bool):
        if enabled:
            if self.local_mute:
                self.signals.log.emit('FRN PTT blockiert: eigenes Mikrofon stummgeschaltet.')
                return

            if not self.cfg.audio_enabled:
                self.signals.error.emit("Audio ist nicht aktiviert.")
                return
            if self.state not in ("IDLE", "TX_WAITING"):
                self.signals.error.emit(
                    f"FRN ist gerade nicht sendebereit (Status {self.state})."
                )
                return
            self.want_tx.set()
            self.tx_granted_evt.clear()
            self._set_state("TX_WAITING")
            try:
                self._send_line("TX0")
            except Exception as exc:
                self.signals.error.emit(str(exc))
        else:
            self.want_tx.clear()
            if self.state == "TX_WAITING":
                try:
                    self._send_line("RX0")
                except Exception:
                    pass
                self.tx_granted_evt.clear()
                self.signals.tx_granted.emit(False)
                self._set_state("IDLE")

    def _start_audio(self):
        if not self.cfg.audio_enabled:
            return
        if sd is None:
            raise RuntimeError(
                "Python-Modul sounddevice fehlt. Die FunkGateway-venv sollte es enthalten."
            )
        self.codec = GsmWav49()
        self.output_stream = sd.RawOutputStream(
            samplerate=FRN_SAMPLE_RATE,
            blocksize=FRN_AUDIO_SAMPLES,
            channels=1,
            dtype="int16",
            device=self.cfg.audio_output,
            latency="low",
        )
        self.output_stream.start()

        self.play_thread = threading.Thread(target=self._play_loop, daemon=True)
        self.play_thread.start()
        self.signals.log.emit(
            "Audio aktiv: GSM 06.10 WAV49, 8 kHz mono. "
            "FRN-RX wird auf den gewählten Ausgang ausgegeben."
        )

    def _wait_audio_workers(self):
        """Wait until RX/TX audio workers no longer use stream/codec resources."""
        current = threading.current_thread()
        for name in ("tx_thread", "play_thread"):
            worker = getattr(self, name, None)
            if worker and worker.is_alive() and worker is not current:
                worker.join(timeout=2.0)
                if worker.is_alive():
                    self.signals.log.emit(
                        f"WARN: {name} läuft nach 2 s noch; Audio-Ressourcen bleiben vorerst offen."
                    )
                    return False
        return True

    def _close_audio(self):
        for stream_name in ("input_stream", "output_stream"):
            stream = getattr(self, stream_name, None)
            if stream:
                try:
                    stream.stop()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass
                setattr(self, stream_name, None)
        if self.codec:
            try:
                self.codec.close()
            except Exception:
                pass
            self.codec = None

    def _play_loop(self):
        while not self.stop_evt.is_set():
            try:
                encoded = self.play_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if self.codec and self.output_stream:
                    pcm = self.codec.decode_packet(encoded)
                    self.signals.rx_audio_level.emit(rms_dbfs(pcm))
                    if not self.local_deaf:
                        self.output_stream.write(pcm)
            except Exception as exc:
                self.signals.error.emit("FRN RX-Audio: " + str(exc))

    def _tx_audio_loop(self):
        try:
            if self.codec is None:
                raise RuntimeError("Audio/Codec ist nicht initialisiert.")
            if self.cfg.pulse_audio_input:
                self.input_proc = subprocess.Popen([
                    "parec", f"--device={self.cfg.pulse_audio_input}",
                    "--format=s16le", f"--rate={FRN_SAMPLE_RATE}", "--channels=1",
                ], stdout=subprocess.PIPE)
                self.signals.log.emit(
                    f"FRN TX-Audio: Funk-RX über {self.cfg.pulse_audio_input}."
                )
                pending = bytearray()
                while (
                    not self.stop_evt.is_set()
                    and self.want_tx.is_set()
                    and self.tx_granted_evt.is_set()
                ):
                    need = FRN_AUDIO_SAMPLES * 2 - len(pending)
                    chunk = self.input_proc.stdout.read(need)
                    if not chunk:
                        raise RuntimeError("Funk-RX-Audiopfad wurde beendet.")
                    pending.extend(chunk)
                    if len(pending) < FRN_AUDIO_SAMPLES * 2:
                        continue
                    pcm = bytes(pending[:FRN_AUDIO_SAMPLES * 2])
                    del pending[:FRN_AUDIO_SAMPLES * 2]
                    self.signals.audio_level.emit(rms_dbfs(pcm))
                    if not self.local_mute:
                        self._send(b"TX1\r\n" + self.codec.encode_packet(pcm))
            else:
                if sd is None:
                    raise RuntimeError("sounddevice ist nicht initialisiert.")
                self.input_stream = sd.RawInputStream(
                    samplerate=FRN_SAMPLE_RATE,
                    blocksize=FRN_AUDIO_SAMPLES,
                    channels=1,
                    dtype="int16",
                    device=self.cfg.audio_input,
                    latency="low",
                )
                self.input_stream.start()
                self.signals.log.emit("FRN TX-Audio gestartet.")
                while (
                    not self.stop_evt.is_set()
                    and self.want_tx.is_set()
                    and self.tx_granted_evt.is_set()
                ):
                    pcm, overflow = self.input_stream.read(FRN_AUDIO_SAMPLES)
                    pcm = bytes(pcm)
                    self.signals.audio_level.emit(rms_dbfs(pcm))
                    if overflow:
                        self.signals.log.emit("WARN: Audio-Eingang hatte einen Overflow.")
                    if not self.local_mute:
                        self._send(b"TX1\r\n" + self.codec.encode_packet(pcm))
            if self.sock and not self.stop_evt.is_set():
                self._send_line("RX0")
                self._set_state("IDLE")
        except Exception as exc:
            self.signals.error.emit("FRN TX-Audio: " + str(exc))
            self.want_tx.clear()
        finally:
            if self.input_stream:
                try:
                    self.input_stream.stop()
                    self.input_stream.close()
                except Exception:
                    pass
                self.input_stream = None
            if self.input_proc:
                try:
                    self.input_proc.terminate()
                except Exception:
                    pass
                self.input_proc = None
            self.tx_granted_evt.clear()
            self.signals.tx_granted.emit(False)
            self.signals.log.emit("FRN TX-Audio beendet.")

    def _start_tx_thread(self):
        if self.tx_thread and self.tx_thread.is_alive():
            return
        self.tx_thread = threading.Thread(target=self._tx_audio_loop, daemon=True)
        self.tx_thread.start()

    def _login_string(self, password: str):
        c = self.cfg
        return (
            "CT:"
            f"<VX>{html.escape(c.protocol_version)}</VX>"
            f"<EA>{html.escape(c.email)}</EA>"
            f"<PW>{html.escape(password)}</PW>"
            f"<ON>{html.escape(c.callsign_user)}</ON>"
            f"<CL>{c.client_type}</CL>"
            f"<BC>{html.escape(c.band_channel)}</BC>"
            f"<DS>{html.escape(c.description)}</DS>"
            f"<NN>{html.escape(c.country)}</NN>"
            f"<CT>{html.escape(c.city_part)}</CT>"
            f"<NT>{html.escape(c.net)}</NT>"
        )

    def _recv_login_line(self, deadline):
        while time.monotonic() < deadline and not self.stop_evt.is_set():
            idx = self._line_end()
            if idx is not None:
                return self._pop_line(idx)
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                raise ConnectionError("FRN-Server hat die Verbindung beendet.")
            self.buf.extend(chunk)
        raise TimeoutError("Zeitüberschreitung bei FRN-Anmeldung.")

    def _line_end(self):
        for i, b in enumerate(self.buf):
            if b in (10, 13):
                return i
        return None

    def _pop_line(self, idx):
        raw = bytes(self.buf[:idx])
        consume = idx + 1
        if self.buf[idx] == 13 and consume < len(self.buf) and self.buf[consume] == 10:
            consume += 1
        del self.buf[:consume]
        return decode_frn(raw, "cp1252")

    def _begin_list(self, kind):
        self.list_kind = kind
        self.list_remaining = None
        self.list_items = []

    def _finish_list(self):
        items = self.list_items
        kind = self.list_kind
        if kind == "CLIENT_LIST":
            self.client_list = list(items)
            self.signals.clients.emit(len(items))
            self.signals.participant_list.emit(self._parsed_clients())
            self.signals.log.emit(f"FRN Clientliste: {len(items)} Teilnehmer.")
        elif kind == "TEXT_MESSAGE":
            # Some FRN servers send one private message as three list entries:
            # UUID of sender, plain message text, and a trailing "P" marker.
            # Recognize only this unambiguous structure; other server
            # variants retain their established per-entry handling.
            import uuid
            ordinary_entries = items
            if len(items) == 3 and str(items[2]).strip() == "P":
                try:
                    sender_id = str(uuid.UUID(str(items[0]).strip()))
                except (ValueError, AttributeError):
                    sender_id = None
                message_text = html.unescape(str(items[1])).strip()
                if sender_id and message_text and "<" not in message_text:
                    sender_name = next((
                        self._client_field(client, "ON")
                        for client in self.client_list
                        if self._client_field(client, "ID").casefold() == sender_id.casefold()
                    ), "") or "FRN"
                    self.signals.text_message.emit({
                        "sender": sender_name,
                        "sender_id": sender_id,
                        "private": True,
                        "message": message_text[:2000],
                    })
                    ordinary_entries = []
            for entry in ordinary_entries[:100]:
                raw = str(entry)
                if len(raw) > MAX_LINE:
                    continue
                sender = self._client_field(raw, "ON")
                message = self._client_field(raw, "MS")
                if not message:
                    message = html.unescape(raw).strip() if "<" not in raw else ""
                if message:
                    self.signals.text_message.emit({
                        "sender": sender or "FRN",
                        "message": message[:2000],
                    })
        elif kind == "NET_NAMES":
            cleaned = []
            seen = set()
            for item in items:
                name = html.unescape(str(item)).strip()
                # Manche Server können XML-artige Felder liefern; bei einfachem
                # FRN ist der Listeneintrag normalerweise direkt der Raumname.
                m = re.search(r"<NT>(.*?)</NT>", name)
                if m:
                    name = html.unescape(m.group(1)).strip()
                if name and name not in seen:
                    seen.add(name)
                    cleaned.append(name)
            self.server_room_names = cleaned
            self.signals.server_room_list.emit(list(cleaned))
            self.signals.log.emit(
                f"FRN Server-Raumliste (NET_NAMES): {len(cleaned)} Räume."
            )
        self.list_kind = None
        self.list_remaining = None
        self.list_items = []
        self._set_state("IDLE")

    def _consume_list(self):
        progressed = False
        while True:
            idx = self._line_end()
            if idx is None:
                return progressed
            line = self._pop_line(idx)
            progressed = True
            if self.list_remaining is None:
                self.list_remaining = parse_int(
                    line, 0, MAX_CLIENTS_PER_NET, "FRN-Listenlänge"
                )
                if self.list_remaining == 0:
                    self._finish_list()
                    return True
            else:
                self.list_items.append(line)
                self.list_remaining -= 1
                if self.list_remaining == 0:
                    self._finish_list()
                    return True

    @staticmethod
    def _client_field(line, tag):
        m = re.search(rf"<{tag}>(.*?)</{tag}>", line or "")
        return html.unescape(m.group(1)).strip() if m else ""

    def _parsed_clients(self):
        result = []
        for idx, line in enumerate(self.client_list, start=1):
            result.append({
                "index": idx,
                "name": self._client_field(line, "ON") or f"Client #{idx}",
                "id": self._client_field(line, "ID"),                "type": self._client_field(line, "CL"),
                "band": self._client_field(line, "BC"),
                "country": self._client_field(line, "NN"),
                "city": self._client_field(line, "CT"),
                "description": self._client_field(line, "DS"),
                "raw": line,
            })
        return result

    def _talker_name(self, index):
        if 1 <= index <= len(self.client_list):
            line = self.client_list[index - 1]
            name = self._client_field(line, "ON")
            if name:
                return name
        return f"Client #{index}" if index else ""

    def _parse(self):
        while self.buf and not self.stop_evt.is_set():
            if self.state == "WAIT_TX_INDEX":
                if len(self.buf) < 2:
                    return
                self.current_talker_index = int.from_bytes(self.buf[:2], "big")
                del self.buf[:2]
                self._set_state("TX_AUDIO")
                self.tx_granted_evt.set()
                self.signals.tx_granted.emit(True)
                if self.want_tx.is_set():
                    self._start_tx_thread()
                else:
                    self.tx_granted_evt.clear()
                    self.signals.tx_granted.emit(False)
                    self._send_line("RX0")
                    self._set_state("IDLE")
                continue

            if self.state == "RX_CLIENT_LIST_HEADER":
                if len(self.buf) < 2:
                    return
                active = int.from_bytes(self.buf[:2], "big")
                del self.buf[:2]
                self.current_talker_index = active
                self._begin_list("CLIENT_LIST")
                self._set_state("RX_CLIENT_LIST")
                continue

            if self.state in ("RX_CLIENT_LIST", "RX_LIST"):
                if not self._consume_list():
                    return
                continue

            if self.state == "RX_AUDIO":
                need = CLIENT_INDEX_SIZE + FRN_AUDIO_PACKET_SIZE
                if len(self.buf) < need:
                    return
                index = int.from_bytes(self.buf[:2], "big")
                packet = bytes(self.buf[2:need])
                del self.buf[:need]
                talker = self._talker_name(index)
                self.signals.rx_talker.emit(talker)
                if self.cfg.audio_enabled:
                    try:
                        self.play_queue.put_nowait(packet)
                    except queue.Full:
                        try:
                            self.play_queue.get_nowait()
                            self.play_queue.put_nowait(packet)
                        except Exception:
                            pass
                self._set_state("IDLE")
                self._send_line("P", log=False)
                continue

            cmd = self.buf[0]
            del self.buf[0]

            if cmd == 0:  # DT_IDLE
                self.signals.rx_talker.emit("")
                if not self.want_tx.is_set():
                    self._set_state("IDLE")
                    self._send_line("P", log=False)
            elif cmd == 1:  # DT_DO_TX
                self._set_state("WAIT_TX_INDEX")
            elif cmd == 2:  # DT_VOICE_BUFFER
                self._set_state("RX_AUDIO")
            elif cmd == 3:  # DT_CLIENT_LIST
                self._set_state("RX_CLIENT_LIST_HEADER")
            elif 4 <= cmd <= 10:
                names = {
                    4: "TEXT_MESSAGE", 5: "NET_NAMES", 6: "ADMIN_LIST",
                    7: "ACCESS_LIST", 8: "BLOCK_LIST", 9: "MUTE_LIST",
                    10: "ACCESS_MODE",
                }
                self._begin_list(names.get(cmd, f"LIST_{cmd}"))
                self._set_state("RX_LIST")
            else:
                self.signals.log.emit(f"WARN: Unbekanntes FRN-Datentyp-Byte {cmd}")
                self._set_state("IDLE")

    def _run(self):
        self.signals.connected.emit(False)
        try:
            self._set_state("DYNAMIC_PASSWORD")
            try:
                dyn = get_dynamic_password(
                    self.cfg.manager_key,
                    self.cfg.email,
                    self.cfg.main_password,
                )
                self.signals.log.emit(
                    f"Dynamisches Passwort von {MANAGERS[self.cfg.manager_key]['label']} erhalten."
                )
            except Exception as exc:
                if not self.cfg.allow_main_password_fallback:
                    raise RuntimeError(
                        f"SYSTEMMANAGER: Dynamisches Passwort nicht verfügbar ({exc}); "
                        "Serveranmeldung aus Sicherheitsgründen nicht versucht. "
                        "Der Hauptpasswort-Fallback ist deaktiviert."
                    ) from exc
                dyn = self.cfg.main_password
                self.signals.log.emit(
                    f"SYSTEMMANAGER: Dynamisches Passwort nicht verfügbar ({exc}); "
                    "Hauptpasswort-Fallback ist ausdrücklich aktiviert – "
                    "FRN-Hauptpasswort wird für diesen Server-Login verwendet."
                )

            self._set_state("CONNECTING")
            self.signals.log.emit(
                f"Verbinde {self.cfg.server}:{self.cfg.port} / Raum {self.cfg.net!r} …"
            )
            self.sock = socket.create_connection(
                (self.cfg.server, self.cfg.port), timeout=10
            )
            self.sock.settimeout(0.5)
            self.signals.connected.emit(True)

            # Audio starts only after the server accepted login stage 2.
            self._set_state("LOGGING_IN_1")
            self._send(
                (self._login_string(dyn) + "\r\n").encode("cp1252", "replace"),
                "CT:<Anmeldedaten ausgeblendet>",
            )

            line1_raw = self._recv_login_line(time.monotonic() + 12)
            self.signals.log.emit("RX Login 1: " + repr(line1_raw))
            # Manche FRN-Servervarianten stellen der eigentlichen Login-1-Antwort
            # ein NUL-/Steuerbyte voran (z. B. "\\x002014003"). Für die
            # Protokollprüfung entfernen wir ausschließlich führende C0-
            # Steuerzeichen; die unveränderte Rohantwort bleibt im Diagnose-Log.
            line1 = line1_raw.lstrip("".join(chr(i) for i in range(0x20)))
            # FRN-Servervarianten beantworten die erste Login-Stufe unterschiedlich.
            # Klassische Server liefern eine 7-stellige Kennung (oder "0").
            # Neuere/alternative Server können stattdessen die vom Client gesendete
            # VX-Kennung spiegeln. Das ist z. B. bei einer 8-stelligen Datumskennung
            # wie 20261016 legitim. Wir akzeptieren daher ausdrücklich nur die
            # bekannten klassischen Formen ODER exakt unsere eigene VX-Kennung.
            if not (len(line1) == 7 or line1 == "0" or line1 == str(self.cfg.protocol_version)):
                raise RuntimeError(
                    "FRN-PROTOKOLL: Unerwartete FRN-Protokollantwort: "
                    + repr(line1_raw)
                    + (f" (bereinigt: {line1!r})" if line1 != line1_raw else "")
                )

            self._set_state("LOGGING_IN_2")
            line2 = self._recv_login_line(time.monotonic() + 12)
            safe = line2.replace(dyn, "***").replace(self.cfg.main_password, "***")
            self.signals.log.emit("RX Login 2: " + safe)
            if "<AL>WRONG</AL>" in line2:
                raise RuntimeError("FRN-SERVER: Anmeldung abgelehnt – Zugangsdaten falsch/unbekannt.")
            if "<AL>BLOCK</AL>" in line2:
                raise RuntimeError(
                    "FRN-SERVER BLOCK: Server hat den Zugriff blockiert. "
                    f"Aktuelle Identität: CL={self.cfg.client_type}, "
                    f"VX={self.cfg.protocol_version}. "
                    "Der Server akzeptiert diesen FunkGateway-Client in dieser Klasse/Version nicht."
                )

            if self.cfg.audio_enabled:
                self._start_audio()

            self._set_state("IDLE")
            self._send_line("RX0")
            self._send_line("ST:0")
            self.signals.log.emit(
                "FRN verbunden. Native Audioverbindung ist aktiv."
                if self.cfg.audio_enabled else
                "FRN verbunden. Audio ist deaktiviert."
            )

            next_ping = time.monotonic() + 2.0
            while not self.stop_evt.is_set():
                try:
                    data = self.sock.recv(65536)
                    if not data:
                        raise ConnectionError("FRN-Server hat getrennt.")
                    self.buf.extend(data)
                    self._parse()
                    next_ping = time.monotonic() + 2.0
                except socket.timeout:
                    pass

                if (
                    time.monotonic() >= next_ping
                    and self.state == "IDLE"
                    and not self.want_tx.is_set()
                ):
                    self._send_line("P", log=False)
                    next_ping = time.monotonic() + 2.0

        except Exception as exc:
            if not self.stop_evt.is_set():
                self.signals.error.emit(str(exc))
                self._set_state("ERROR")
        finally:
            # Every network-thread exit also stops RX/TX audio workers.
            self.stop_evt.set()
            self.want_tx.clear()
            self.tx_granted_evt.clear()
            if self._wait_audio_workers():
                self._close_audio()
            s = self.sock
            self.sock = None
            if s:
                try:
                    s.close()
                except Exception:
                    pass
            self.signals.connected.emit(False)
            self.signals.tx_granted.emit(False)
            if self.stop_evt.is_set():
                self._set_state("DISCONNECTED")

