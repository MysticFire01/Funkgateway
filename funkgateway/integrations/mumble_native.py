from __future__ import annotations

import audioop
import math
import subprocess
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
    chatReceived = Signal(object)
    aclReceived = Signal(object)
    aclDenied = Signal(str)
    registeredUsersReceived = Signal(object)

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
        self._gateway_rx_active = False
        self._rf_capture_thread = None
        self._rf_capture_stop = threading.Event()
        self._rf_proc = None
        self._playback_enabled = True
        self._playback_device = None
        self._playback_stream = None
        self._playback_lock = threading.RLock()
        self._speaker_lock = threading.Lock()
        self._speaker_times = {}
        self._speaker_modes = {}
        self._own_tx_active = False
        self._certfile = ""
        self._keyfile = ""
        self._playback_volume = 1.0
        self._user_volumes = {}
        self._local_muted_sessions = set()
        self._volume_server = ""

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
        self._volume_server = f"{host.casefold()}:{int(port)}"
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
                reconnect=False, stereo=False, debug=False,
            )
            self._mumble = mumble
            try:
                mumble.set_application_string("FunkGateway Linux")
            except Exception:
                pass
            mumble.set_receive_sound(True)
            mumble.callbacks.set_callback(cb_sound, self._sound_received)
            try:
                from pymumble_py3.constants import PYMUMBLE_CLBK_TEXTMESSAGERECEIVED
            except ImportError:
                from pymumble_py3.callbacks import PYMUMBLE_CLBK_TEXTMESSAGERECEIVED
            mumble.callbacks.set_callback(PYMUMBLE_CLBK_TEXTMESSAGERECEIVED, self._chat_received)
            try:
                from pymumble_py3.constants import PYMUMBLE_CLBK_ACLRECEIVED, PYMUMBLE_CLBK_PERMISSIONDENIED
            except ImportError:
                from pymumble_py3.callbacks import PYMUMBLE_CLBK_ACLRECEIVED, PYMUMBLE_CLBK_PERMISSIONDENIED
            mumble.callbacks.set_callback(PYMUMBLE_CLBK_ACLRECEIVED,self._acl_received)
            mumble.callbacks.set_callback(PYMUMBLE_CLBK_PERMISSIONDENIED,self._acl_denied)
            # pymumble currently parses UserList but discards it. Intercept
            # only this packet and leave all other dispatch behavior intact.
            from pymumble_py3 import mumble_pb2
            from pymumble_py3.constants import PYMUMBLE_MSG_TYPES_USERLIST
            old_dispatch=mumble.dispatch_control_message
            from pymumble_py3.constants import PYMUMBLE_MSG_TYPES_CHANNELSTATE
            self._channel_descriptions={}
            self._description_requests=set()
            def dispatch_with_userlist(packet_type,payload):
                if packet_type==PYMUMBLE_MSG_TYPES_CHANNELSTATE:
                    msg=mumble_pb2.ChannelState()
                    msg.ParseFromString(payload)
                    if msg.HasField("description"):
                        self._channel_descriptions[int(msg.channel_id)]=str(msg.description)
                if packet_type==PYMUMBLE_MSG_TYPES_USERLIST:
                    msg=mumble_pb2.UserList()
                    msg.ParseFromString(payload)
                    rows=[
                        {"user_id":int(u.user_id),"name":str(u.name),
                         "last_seen":str(u.last_seen),
                         "last_channel":int(u.last_channel) if u.HasField("last_channel") else None}
                        for u in msg.users
                     ]
                    self._registered_users_cache=rows
                    self.registeredUsersReceived.emit(rows)
                return old_dispatch(packet_type,payload)
            mumble.dispatch_control_message=dispatch_with_userlist
            self._registered_users_cache=[]
            mumble.start()
            mumble.is_ready()
            state = int(getattr(mumble, "connected", 0))
            session = getattr(mumble.users, "myself_session", None)
            if state != 2 or session is None:
                raise RuntimeError(
                    f"Mumble-Anmeldung nicht abgeschlossen (Status={state}, Session={session})."
                )
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

            # Open the microphone only when PTT is first pressed.
            # This avoids holding a physical ALSA device unnecessarily.
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
            self._stop_rf_capture()
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
        self._gateway_rx_active = False
        self._stop_rf_capture()
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

    def volume_key(self, name):
        return f"{self._volume_server}|{str(name).strip().casefold()}"

    def set_playback_volume(self, percent):
        self._playback_volume = max(0.0, min(2.0, float(percent) / 100))

    def set_user_volumes(self, values):
        self._user_volumes = {
            str(key): max(0.0, min(2.0, float(value) / 100))
            for key, value in dict(values or {}).items()
        }

    def user_volume(self, name):
        return int(round(100 * self._user_volumes.get(self.volume_key(name), 1.0)))

    def set_user_volume(self, name, percent):
        key = self.volume_key(name)
        gain = max(0.0, min(2.0, float(percent) / 100))
        if gain == 1.0:
            self._user_volumes.pop(key, None)
        else:
            self._user_volumes[key] = gain

    def _chat_received(self, message):
        try:
            actor = int(message.actor) if message.HasField("actor") else None
            self.chatReceived.emit({
                "actor": actor,
                "sessions": [int(s) for s in message.session],
                "channels": [int(c) for c in message.channel_id],
                "message": str(message.message or ""),
            })
        except Exception as exc:
            self.error.emit("Mumble Chat: " + str(exc))

    def send_chat(self, message, session=None):
        if not self._connected or self._mumble is None:
            raise RuntimeError("Mumble ist nicht verbunden.")
        from html import escape
        message = str(message or "").strip()
        if not message:
            return None
        if len(message) > 4000:
            raise RuntimeError("Maximal 4000 Zeichen pro Nachricht.")
        payload = escape(message)
        if session is None:
            channel = self._mumble.my_channel()
            if channel is None:
                raise RuntimeError("Kein aktueller Channel vorhanden.")
            channel.send_text_message(payload)
            return "Channel"
        try:
            user = self._mumble.users[int(session)]
        except (ValueError, TypeError, KeyError) as exc:
            raise RuntimeError("Empfänger nicht mehr verbunden.") from exc
        user.send_text_message(payload)
        return str(self._prop(user, "name", session))

    def chat_sender_name(self, actor):
        if actor is None:
            return "Server"
        try:
            return str(self._prop(self._mumble.users[int(actor)], "name", actor))
        except Exception:
            return f"Session {actor}"

    def configure_audio(self, input_device=None, output_device=None, playback=True):
        self._capture_device = input_device
        self._playback_device = output_device
        self._playback_enabled = bool(playback)
        if self._connected:
            self._ensure_playback()
            if self._pc_ptt_enabled:
                self._start_capture()

    def set_self_mute(self, enabled):
        if not self._connected or self._mumble is None:
            raise RuntimeError("Mumble ist nicht verbunden.")
        myself = self._mumble.users.myself
        if enabled:
            self._pc_ptt_active = False
            myself.mute()
        else:
            myself.unmute()

    def set_self_deaf(self, enabled):
        if not self._connected or self._mumble is None:
            raise RuntimeError("Mumble ist nicht verbunden.")
        myself = self._mumble.users.myself
        if enabled:
            myself.deafen()
        else:
            myself.undeafen()

    def set_local_user_mute(self, session, enabled):
        session = int(session)
        if enabled:
            self._local_muted_sessions.add(session)
        else:
            self._local_muted_sessions.discard(session)

    def set_server_user_mute(self, session, enabled):
        if not self._connected or self._mumble is None:
            raise RuntimeError("Mumble ist nicht verbunden.")
        user = self._mumble.users[int(session)]
        if enabled:
            user.mute()
        else:
            user.unmute()

    def set_server_user_deaf(self, session, enabled):
        if not self._connected or self._mumble is None:
            raise RuntimeError("Mumble ist nicht verbunden.")
        user = self._mumble.users[int(session)]
        if enabled:
            user.deafen()
        else:
            user.undeafen()

    def set_pc_ptt(self, active):
        self._pc_ptt_active = bool(active) and self._pc_ptt_enabled and self._connected
        self._own_tx_active = bool(self._pc_ptt_active or self._gateway_rx_active)
        if self._pc_ptt_active and not (self._capture_thread and self._capture_thread.is_alive()):
            self._start_capture()

    def set_gateway_rx(self, active):
        """Key native Mumble from RF RX independently of PC-user PTT."""
        active = bool(active and self._connected and not self._stop.is_set())
        if active == self._gateway_rx_active:
            return
        self._gateway_rx_active = active
        self._own_tx_active = bool(active or self._pc_ptt_active)
        if active and not (self._rf_capture_thread and self._rf_capture_thread.is_alive()):
            self._rf_capture_stop.clear()
            self._rf_capture_thread = threading.Thread(
                target=self._rf_capture_worker, daemon=True)
            self._rf_capture_thread.start()
        self._emit_participants()

    def _stop_rf_capture(self):
        self._gateway_rx_active = False
        self._rf_capture_stop.set()
        proc = self._rf_proc
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
        thread = self._rf_capture_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.5)
        self._rf_capture_thread = None
        self._rf_proc = None

    def _rf_capture_worker(self):
        """Read the actual gateway RX virtual source, not the PC microphone."""
        proc = None
        try:
            proc = subprocess.Popen(
                ["parec", "--device=funkgateway_rx_source", "--raw",
                 "--format=s16le", "--rate=48000", "--channels=1"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
            self._rf_proc = proc
            while not self._rf_capture_stop.is_set() and not self._stop.is_set():
                frame = proc.stdout.read(1920)
                if not frame:
                    raise RuntimeError("FunkGateway_RX_Input liefert keine Audiodaten")
                if not self._gateway_rx_active or not self._connected:
                    continue
                mumble = self._mumble
                if mumble is not None:
                    mumble.sound_output.add_sound(frame)
        except Exception as exc:
            if not self._rf_capture_stop.is_set() and not self._stop.is_set():
                self._gateway_rx_active = False
                self._own_tx_active = bool(self._pc_ptt_active)
                self.error.emit("Mumble Funk-RX-Audio: " + str(exc))
        finally:
            if proc is not None:
                try:
                    proc.terminate()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=0.5)
                except Exception:
                    pass
            self._rf_proc = None

    def channel_details(self, channel_id):
        if not self.connected or self._mumble is None:
            raise RuntimeError("Mumble ist nicht verbunden.")
        cid=int(channel_id)
        channel=self._mumble.channels[cid]
        description=self._prop(channel,"description",None)
        desc_hash=self._prop(channel,"description_hash",None)
        if description is None:
            description=getattr(self,"_channel_descriptions",{}).get(cid)
        if description is None and desc_hash:
            description=self._mumble.blobs.get(desc_hash)
            requested=getattr(self,"_description_requests",set())
            if description is None and cid not in requested:
                requested.add(cid)
                self._description_requests=requested
                # Mumble RequestBlob.channel_description contains channel IDs,
                # NOT SHA1 hashes. pymumble's blob helper mistakenly unpacks
                # the hash into five integers, so send the correct request.
                from pymumble_py3 import mumble_pb2
                from pymumble_py3.constants import PYMUMBLE_MSG_TYPES_REQUESTBLOB
                request=mumble_pb2.RequestBlob()
                request.channel_description.append(cid)
                self._mumble.send_message(PYMUMBLE_MSG_TYPES_REQUESTBLOB,request)
        if isinstance(description,bytes):
            description=description.decode("utf-8","replace")
        return {
            "name":str(self._prop(channel,"name","") or ""),
            "description":str(description) if description is not None else "",
            "description_ready":description is not None or not bool(desc_hash),
            "description_state":("loaded" if description is not None else
                                 "waiting_for_blob" if desc_hash else "no_description_hash"),
            "position":int(self._prop(channel,"position",0) or 0),
            "temporary":bool(self._prop(channel,"temporary",False)),
            "max_users":int(self._prop(channel,"max_users",0) or 0),
        }

    def moderate_user(self,session,ban=False,reason=""):
        if not self.connected or self._mumble is None:
            raise RuntimeError("Mumble ist nicht verbunden.")
        target=int(session)
        myself=getattr(self._mumble.users,"myself_session",None)
        if myself is not None and target==int(myself):
            raise ValueError("Eigene Verbindung kann hier nicht gekickt oder gebannt werden.")
        if target not in self._mumble.users:
            raise ValueError("Benutzer ist nicht mehr mit dem Server verbunden.")
        reason=str(reason or "").strip()[:400]
        if ban:
            self._mumble.users[target].ban(reason=reason)
        else:
            self._mumble.users[target].kick(reason=reason)

    def cached_registered_users(self):
        return list(getattr(self,"_registered_users_cache",[]) or []) if self.connected else []

    def request_registered_users(self):
        if not self.connected or self._mumble is None:
            raise RuntimeError("Mumble ist nicht verbunden.")
        from pymumble_py3 import mumble_pb2
        from pymumble_py3.constants import PYMUMBLE_MSG_TYPES_USERLIST
        self._mumble.send_message(PYMUMBLE_MSG_TYPES_USERLIST,mumble_pb2.UserList())

    def remove_registered_user(self,user_id):
        if not self.connected or self._mumble is None:
            raise RuntimeError("Mumble ist nicht verbunden.")
        uid=int(user_id)
        if uid<=0:
            raise ValueError("System-/SuperUser-Konto kann hier nicht entfernt werden.")
        # Mumble protocol: an entry containing only user_id requests deletion.
        from pymumble_py3 import mumble_pb2
        from pymumble_py3.constants import PYMUMBLE_MSG_TYPES_USERLIST
        message=mumble_pb2.UserList()
        message.users.add(user_id=uid)
        self._mumble.send_message(PYMUMBLE_MSG_TYPES_USERLIST,message)

    def registered_user_names(self):
        """Only names actually reported by the connected server; no guessing."""
        names={}
        if not self.connected or self._mumble is None:
            return names
        try:
            for _session,user in list(self._mumble.users.items()):
                raw=self._prop(user,"user_id",None)
                name=str(self._prop(user,"name","") or "").strip()
                if raw is None or not name:
                    continue
                uid=int(raw)
                if uid>=0:
                    names[uid]=name
        except Exception:
            pass
        return names

    def request_channel_acl(self,channel_id):
        if not self.connected or self._mumble is None:
            raise RuntimeError("Mumble ist nicht verbunden.")
        self._mumble.channels[int(channel_id)].request_acl()

    def _acl_received(self,message):
        # Only actual server responses are surfaced; no cached ACL disclosure.
        try:
            data={
                "channel_id":int(message.channel_id),
                "inherit_acls":bool(message.inherit_acls),
                "groups":[{"name":str(g.name),"inherit":bool(g.inherit),
                           "inheritable":bool(g.inheritable),
                           "add":list(g.add),"remove":list(g.remove),
                           "inherited_members":list(g.inherited_members),
                           "inherited":bool(g.inherited)}
                          for g in message.groups],
                "rules":[{"group":str(a.group) if a.HasField("group") else "",
                          "user_id":int(a.user_id) if a.HasField("user_id") else None,
                          "apply_here":bool(a.apply_here),
                          "apply_subs":bool(a.apply_subs),
                          "inherited":bool(a.inherited),
                          "grant":int(a.grant),"deny":int(a.deny)}
                         for a in message.acls],
            }
            self.aclReceived.emit(data)
        except Exception as exc:
            self.aclDenied.emit("ACL-Antwort konnte nicht verarbeitet werden: "+str(exc))

    def _acl_denied(self,message):
        details=str(getattr(message,"reason","") or "")
        self.aclDenied.emit("Der Mumble-Server verweigert diese Aktion oder ACL-Einsicht."
                            +((" Grund: "+details) if details else ""))

    def save_channel_acl(self,channel_id,inherit_acls,groups,rules):
        if not self.connected or self._mumble is None:
            raise RuntimeError("Mumble ist nicht verbunden.")
        from pymumble_py3 import messages
        # Only local rules/groups are submitted, not inherited ACL entries.
        cmd=messages.UpdateACL(channel_id=int(channel_id),
              inherit_acls=bool(inherit_acls),chan_group=groups,chan_acl=rules)
        self._mumble.execute_command(cmd)

    def create_channel(self,parent_id,name,temporary=False):
        if not self.connected or self._mumble is None:
            raise RuntimeError("Mumble ist nicht verbunden.")
        name=str(name).strip()
        if not name:
            raise ValueError("Raumname fehlt.")
        # Actual permission checks happen on the Mumble server.
        self._mumble.channels.new_channel(int(parent_id),name,bool(temporary))

    def delete_channel(self,channel_id):
        if not self.connected or self._mumble is None:
            raise RuntimeError("Mumble ist nicht verbunden.")
        channel_id=int(channel_id)
        if channel_id==0:
            raise ValueError("Der Root-Raum darf nicht gelöscht werden.")
        if channel_id not in self._mumble.channels:
            raise ValueError("Der Raum existiert nicht mehr.")
        # This submits the removal request; the server enforces its ACL.
        self._mumble.channels.remove_channel(channel_id)

    def edit_channel(self,channel_id,name,description,position):
        if not self.connected or self._mumble is None:
            raise RuntimeError("Mumble ist nicht verbunden.")
        if int(channel_id)==0:
            raise ValueError("Der Root-Raum kann hier nicht bearbeitet werden.")
        channel=self._mumble.channels[int(channel_id)]
        if not str(name).strip():
            raise ValueError("Raumname fehlt.")
        if str(name).strip()!=str(self._prop(channel,"name","") or ""):
            channel.rename_channel(str(name).strip())
        if str(description)!=str(self._prop(channel,"description","") or ""):
            channel.set_channel_description(str(description))
        if int(position)!=int(self._prop(channel,"position",0) or 0):
            channel.set_channel_position(int(position))

    def set_channel_max_users(self,channel_id,max_users):
        if not self.connected or self._mumble is None:
            raise RuntimeError("Mumble ist nicht verbunden.")
        cid=int(channel_id)
        if cid==0:
            raise ValueError("Das Nutzerlimit des Root-Raums ist hier nicht änderbar.")
        maximum=int(max_users)
        if maximum<0 or maximum>100000:
            raise ValueError("Ungültige maximale Nutzerzahl.")
        channel=self._mumble.channels[cid]
        if maximum==int(self._prop(channel,"max_users",0) or 0):
            return
        from pymumble_py3 import mumble_pb2
        from pymumble_py3.constants import PYMUMBLE_MSG_TYPES_CHANNELSTATE
        request=mumble_pb2.ChannelState()
        request.channel_id=cid
        request.max_users=maximum
        self._mumble.send_message(PYMUMBLE_MSG_TYPES_CHANNELSTATE,request)

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
                "position": int(self._prop(ch, "position", 0) or 0),
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
        if self._stop.is_set() or not self._connected:
            return
        name = str(self._prop(user, "name", "Mumble") or "Mumble")
        try:
            target = int(getattr(soundchunk, "target", 0) or 0)
        except Exception:
            target = 0
        mode = "normal" if target == 0 else ("shout" if target == 1 else "whisper")
        with self._speaker_lock:
            self._speaker_times[name] = time.monotonic()
            self._speaker_modes[name] = mode
        try:
            session = int(self._prop(user, "session", -1))
        except (TypeError, ValueError):
            session = -1
        if session in self._local_muted_sessions:
            return
        pcm = bytes(getattr(soundchunk, "pcm", b""))
        if not pcm:
            return
        self.outputLevel.emit(self._dbfs(pcm))
        if self._playback_enabled:
            gain = self._playback_volume * self._user_volumes.get(self.volume_key(name), 1.0)
            if gain <= 0:
                return
            if gain != 1.0:
                pcm = audioop.mul(pcm, 2, gain)
            try:
                with self._playback_lock:
                    if not self._stop.is_set() and self._connected and self._playback_stream is not None:
                        self._playback_stream.write(pcm)
            except Exception as exc:
                if not self._stop.is_set():
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
            # Mumble assigns nonnegative persistent user IDs to registrations;
            # guests are normally -1. Unknown stays unknown, never guessed.
            raw_uid = self._prop(user, "user_id", None)
            try:
                user_id = int(raw_uid) if raw_uid is not None else None
            except (TypeError, ValueError):
                user_id = None
            result.append({
                "name": name,
                "session": int(self._prop(user, "session", session)),
                "channel_id": cid_i,
                "channel": path_map.get(cid_i, ""),
                "talking": talking,
                "speech_mode": "normal" if is_self and self._own_tx_active else active.get(name, ""),
                "is_self": is_self,
                "user_id": user_id,
                "registered": None if user_id is None else user_id >= 0,
                "current_channel": current_channel is not None and cid_i == current_channel,
                "local_user_mute": int(self._prop(user, "session", session)) in self._local_muted_sessions,
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
        with self._playback_lock:
            if sd is None or not self._playback_enabled:
                self._close_playback()
                return
            if self._playback_stream is not None or self._stop.is_set():
                return
            stream = sd.RawOutputStream(
                samplerate=48000, channels=1, dtype="int16",
                device=self._playback_device, latency="low",
            )
            try:
                stream.start()
                self._playback_stream = stream
            except Exception:
                stream.close()
                raise

    def _close_playback(self):
        # Serialize close with the pymumble receiver callback's write().
        with self._playback_lock:
            stream = self._playback_stream
            self._playback_stream = None
            if stream is not None:
                try:
                    stream.abort()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass

    def _start_capture(self):
        self._stop_capture()
        if sd is None or not self._pc_ptt_enabled:
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
        self._own_tx_active = bool(self._gateway_rx_active)

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
            self._pc_ptt_active = False
            self._own_tx_active = bool(self._gateway_rx_active)
            self.error.emit(
                "Mumble Mikrofon/PTT: " + str(exc)
                + " – Das Eingabegerät ist möglicherweise belegt oder nicht verfügbar. "
                "Unter Mumble → Native Client das System-Standardmikrofon "
                "oder einen PulseAudio/PipeWire-Eingang auswählen und neu verbinden."
            )
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
