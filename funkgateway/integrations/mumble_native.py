from __future__ import annotations

import audioop
import math
import threading
import time
from collections import deque

from PySide6.QtCore import QObject, Signal

try:
    import sounddevice as sd
except Exception:
    sd = None


class MumbleNativeClient(QObject):
    """Native integrated Mumble client for Linux FunkGateway.

    This runs beside (or instead of) the desktop Mumble client. It connects
    directly to the Mumble server and exposes PCM audio, channels and users.
    """

    status = Signal(str)
    connectedChanged = Signal(bool)
    channelChanged = Signal(str)
    participantsChanged = Signal(object)
    speakersChanged = Signal(object)
    inputLevel = Signal(float)
    outputLevel = Signal(float)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mumble = None
        self._thread = None
        self._stop = threading.Event()
        self._connected = False
        self._capture_thread = None
        self._capture_stop = threading.Event()
        self._capture_device = None
        self._pc_ptt_enabled = False
        self._pc_ptt_active = False
        self._playback_enabled = True
        self._playback_device = None
        self._playback_stream = None
        self._speaker_lock = threading.Lock()
        self._speaker_times = {}
        self._speaker_modes = {}
        self._own_tx_active = False
        self._certfile = ""
        self._keyfile = ""

    @property
    def connected(self):
        return bool(self._connected)

    @staticmethod
    def available():
        try:
            import pymumble_py3  # noqa: F401
            import opuslib  # noqa: F401
            return True
        except Exception:
            return False

    @staticmethod
    def _imports():
        import pymumble_py3 as pymumble
        try:
            from pymumble_py3.constants import PYMUMBLE_CLBK_SOUNDRECEIVED
        except Exception:
            from pymumble_py3.callbacks import PYMUMBLE_CLBK_SOUNDRECEIVED
        return pymumble, PYMUMBLE_CLBK_SOUNDRECEIVED

    @staticmethod
    def _prop(obj, name, default=None):
        try:
            value = obj.get_property(name)
            return default if value is None else value
        except Exception:
            pass
        try:
            return obj[name]
        except Exception:
            return default

    def connect_async(self, host, port, nickname, password="", channel_path="",
                      certfile="", keyfile="", playback=True,
                      output_device=None, input_device=None,
                      pc_ptt_enabled=True):
        self.disconnect()
        host = str(host or "").strip()
        nickname = str(nickname or "").strip()
        if not host:
            raise RuntimeError("Mumble-Server fehlt.")
        if not nickname:
            raise RuntimeError("Mumble-Nickname fehlt.")
        self._stop.clear()
        self._certfile = str(certfile or "")
        self._keyfile = str(keyfile or "")
        self._playback_enabled = bool(playback)
        self._playback_device = output_device
        self._capture_device = input_device
        self._pc_ptt_enabled = bool(pc_ptt_enabled)
        self._thread = threading.Thread(
            target=self._worker,
            args=(host, int(port), nickname, str(password or ""), str(channel_path or "")),
            daemon=True,
        )
        self._thread.start()

    def _worker(self, host, port, nickname, password, channel_path):
        try:
            pymumble, cb_sound = self._imports()
            self.status.emit("Native Mumble: verbindet …")
            mumble = pymumble.Mumble(
                host, nickname, port=port, password=password,
                certfile=(self._certfile or None),
                keyfile=(self._keyfile or None),
                reconnect=True, stereo=False, debug=False,
            )
            self._mumble = mumble
            try:
                mumble.set_application_string("FunkGateway Linux")
            except Exception:
                pass
            mumble.set_receive_sound(True)
            mumble.callbacks.set_callback(cb_sound, self._sound_received)
            mumble.start()
            mumble.is_ready()
            if self._stop.is_set():
                mumble.stop()
                return
            self._connected = True
            self.connectedChanged.emit(True)
            self.status.emit("Native Mumble: verbunden als " + nickname)
            self._ensure_playback()

            if channel_path:
                deadline = time.monotonic() + 4.0
                while time.monotonic() < deadline and not self._stop.is_set():
                    if self.move_to_path(channel_path):
                        break
                    time.sleep(0.15)

            if self._pc_ptt_enabled:
                self._start_capture()

            while not self._stop.is_set():
                self._emit_participants()
                try:
                    ch = mumble.my_channel()
                    name = str(self._prop(ch, "name", "") or "")
                    if name:
                        self.channelChanged.emit(name)
                except Exception:
                    pass
                if hasattr(mumble, "is_alive") and not mumble.is_alive():
                    break
                time.sleep(0.5)
        except Exception as exc:
            self.error.emit("Native Mumble: " + str(exc))
        finally:
            self._stop_capture()
            self._close_playback()
            self._connected = False
            self.connectedChanged.emit(False)
            self.status.emit("Native Mumble: getrennt")
            mumble = self._mumble
            self._mumble = None
            if mumble is not None:
                try:
                    mumble.stop()
                except Exception:
                    pass

    def disconnect(self):
        self._stop.set()
        self._pc_ptt_active = False
        self._own_tx_active = False
        self._stop_capture()
        self._close_playback()
        mumble = self._mumble
        if mumble is not None:
            try:
                mumble.stop()
            except Exception:
                pass
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None

    def configure_audio(self, input_device=None, output_device=None, playback=True):
        self._capture_device = input_device
        self._playback_device = output_device
        self._playback_enabled = bool(playback)
        if self._connected:
            self._ensure_playback()
            if self._pc_ptt_enabled:
                self._start_capture()

    def set_pc_ptt(self, active):
        self._pc_ptt_active = bool(active) and self._pc_ptt_enabled and self._connected
        self._own_tx_active = self._pc_ptt_active
        if self._pc_ptt_active and not (self._capture_thread and self._capture_thread.is_alive()):
            self._start_capture()

    def channel_snapshot(self):
        mumble = self._mumble
        if mumble is None or not self._connected:
            return []
        try:
            channels = list(getattr(mumble, "channels", {}).items())
            users = list(getattr(mumble, "users", {}).items())
        except Exception:
            return []
        counts = {}
        current_id = None
        try:
            current_id = int(self._prop(mumble.users.myself, "channel_id", -1))
        except Exception:
            pass
        for _session, user in users:
            cid = self._prop(user, "channel_id", self._prop(user, "channel", None))
            try:
                cid = int(cid)
            except Exception:
                continue
            counts[cid] = counts.get(cid, 0) + 1
        result = []
        for cid, ch in channels:
            try:
                cid_i = int(cid)
            except Exception:
                continue
            parent = self._prop(ch, "parent", None)
            try:
                parent_i = int(parent) if parent is not None else None
            except Exception:
                parent_i = None
            result.append({
                "id": cid_i,
                "parent": parent_i,
                "name": str(self._prop(ch, "name", "") or f"Channel {cid_i}"),
                "users": counts.get(cid_i, 0),
                "current": current_id is not None and cid_i == current_id,
            })
        return result

    def channel_paths(self):
        rows = self.channel_snapshot()
        by_id = {row["id"]: row for row in rows}
        result = []
        for row in rows:
            names = []
            seen = set()
            cid = row["id"]
            while cid in by_id and cid not in seen:
                seen.add(cid)
                cur = by_id[cid]
                names.append(cur["name"])
                parent = cur.get("parent")
                if parent is None or parent == cid:
                    break
                cid = parent
            names.reverse()
            result.append((row["id"], "/".join(names)))
        return sorted(result, key=lambda item: item[1].casefold())

    def move_to_path(self, wanted):
        wanted = str(wanted or "").strip().strip("/")
        if not wanted or self._mumble is None or not self._connected:
            return False
        paths = self.channel_paths()
        match = None
        for cid, path in paths:
            if path.casefold() == wanted.casefold():
                match = cid
                break
        if match is None:
            leaf = wanted.rsplit("/", 1)[-1].casefold()
            hits = [(cid, path) for cid, path in paths if path.rsplit("/",1)[-1].casefold() == leaf]
            if len(hits) == 1:
                match = hits[0][0]
        if match is None:
            return False
        try:
            self._mumble.channels[int(match)].move_in()
            return True
        except Exception as exc:
            self.error.emit("Native Mumble Channel-Wechsel: " + str(exc))
            return False

    def register_current_user(self):
        if not self._connected or self._mumble is None:
            raise RuntimeError("Native Mumble-Verbindung ist nicht aktiv.")
        if not self._certfile or not self._keyfile:
            raise RuntimeError("Verbindung wurde ohne Zertifikat aufgebaut.")
        self._mumble.users.myself.register()
        return True

    def _sound_received(self, user, soundchunk):
        name = str(self._prop(user, "name", "Mumble") or "Mumble")
        try:
            target = int(getattr(soundchunk, "target", 0) or 0)
        except Exception:
            target = 0
        mode = "normal" if target == 0 else ("shout" if target == 1 else "whisper")
        with self._speaker_lock:
            self._speaker_times[name] = time.monotonic()
            self._speaker_modes[name] = mode
        pcm = bytes(getattr(soundchunk, "pcm", b""))
        if not pcm:
            return
        self.outputLevel.emit(self._dbfs(pcm))
        if self._playback_enabled:
            try:
                self._ensure_playback()
                if self._playback_stream is not None:
                    self._playback_stream.write(pcm)
            except Exception as exc:
                self.error.emit("Mumble-Wiedergabe: " + str(exc))

    def participants(self):
        mumble = self._mumble
        if mumble is None or not self._connected:
            return []
        try:
            users = list(getattr(mumble, "users", {}).items())
        except Exception:
            return []
        now = time.monotonic()
        with self._speaker_lock:
            active = {
                name: self._speaker_modes.get(name, "normal")
                for name, ts in self._speaker_times.items()
                if now - ts <= 0.8
            }
        myself_session = None
        current_channel = None
        try:
            myself_session = int(mumble.users.myself_session)
            current_channel = int(self._prop(mumble.users.myself, "channel_id", -1))
        except Exception:
            pass
        path_map = dict(self.channel_paths())
        result = []
        for session, user in users:
            name = str(self._prop(user, "name", "") or "")
            if not name:
                continue
            cid = self._prop(user, "channel_id", self._prop(user, "channel", None))
            try:
                cid_i = int(cid)
            except Exception:
                cid_i = -1
            is_self = myself_session is not None and int(self._prop(user, "session", session)) == myself_session
            talking = (is_self and self._own_tx_active) or name in active
            result.append({
                "name": name,
                "channel_id": cid_i,
                "channel": path_map.get(cid_i, ""),
                "talking": talking,
                "speech_mode": "normal" if is_self and self._own_tx_active else active.get(name, ""),
                "is_self": is_self,
                "current_channel": current_channel is not None and cid_i == current_channel,
                "local_mute": bool(self._prop(user, "self_mute", False)),
                "local_deaf": bool(self._prop(user, "self_deaf", False)),
                "server_mute": bool(self._prop(user, "mute", False) or self._prop(user, "suppress", False)),
                "server_deaf": bool(self._prop(user, "deaf", False)),
            })
        return sorted(result, key=lambda row: (row["channel"].casefold(), row["name"].casefold()))

    def _emit_participants(self):
        rows = self.participants()
        self.participantsChanged.emit(rows)
        speakers = [r["name"] for r in rows if r["talking"]]
        self.speakersChanged.emit(speakers)
        if not speakers:
            self.outputLevel.emit(-120.0)

    def _ensure_playback(self):
        if sd is None or not self._playback_enabled:
            self._close_playback()
            return
        if self._playback_stream is not None:
            return
        self._playback_stream = sd.RawOutputStream(
            samplerate=48000, channels=1, dtype="int16",
            device=self._playback_device, latency="low",
        )
        self._playback_stream.start()

    def _close_playback(self):
        stream = self._playback_stream
        self._playback_stream = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

    def _start_capture(self):
        self._stop_capture()
        if sd is None or not self._pc_ptt_enabled or self._capture_device is None:
            return
        self._capture_stop.clear()
        self._capture_thread = threading.Thread(target=self._capture_worker, daemon=True)
        self._capture_thread.start()

    def _stop_capture(self):
        self._capture_stop.set()
        thread = self._capture_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.5)
        self._capture_thread = None
        self._own_tx_active = False

    def _capture_worker(self):
        try:
            info = sd.query_devices(self._capture_device, "input")
            rate = int(round(float(info.get("default_samplerate") or 48000)))
            if rate < 8000:
                rate = 48000
            block = max(160, int(rate * 0.02))
            rate_state = None
            with sd.RawInputStream(
                samplerate=rate, blocksize=block, channels=1, dtype="int16",
                device=self._capture_device, latency="low",
            ) as stream:
                while not self._capture_stop.is_set() and not self._stop.is_set():
                    data, _overflow = stream.read(block)
                    raw = bytes(data)
                    db = self._dbfs(raw)
                    self.inputLevel.emit(db)
                    if not self._pc_ptt_active:
                        continue
                    if rate != 48000:
                        raw, rate_state = audioop.ratecv(raw, 2, 1, rate, 48000, rate_state)
                    mumble = self._mumble
                    if mumble is not None and self._connected and raw:
                        mumble.sound_output.add_sound(raw)
        except Exception as exc:
            self.error.emit("Mumble Mikrofon/PTT: " + str(exc))
        finally:
            self.inputLevel.emit(-120.0)

    @staticmethod
    def _dbfs(raw):
        if not raw:
            return -120.0
        try:
            rms = audioop.rms(raw, 2)
        except Exception:
            return -120.0
        if rms <= 0:
            return -120.0
        return max(-120.0, 20.0 * math.log10(rms / 32767.0))
