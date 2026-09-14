"""PulseAudio/PipeWire routing and audio-triggered PTT/RX detection."""
import math, struct, subprocess, threading, time
from PySide6.QtCore import QObject, Signal


def run(cmd):
    return subprocess.run(cmd, check=True, text=True, capture_output=True)


def list_sinks():
    try:
        out = run(["pactl", "list", "short", "sinks"]).stdout
        rows=[]
        for line in out.splitlines():
            p=line.split("\t")
            if len(p) >= 2: rows.append((p[1], p[1]))
        return rows
    except Exception:
        return []


def list_sources():
    try:
        out=run(["pactl","list","short","sources"]).stdout
        rows=[]
        for line in out.splitlines():
            p=line.split("\t")
            if len(p)>=2: rows.append((p[1],p[1]))
        return rows
    except Exception:
        return []


def make_virtual_sink():
    if "funkgateway_tx" in [x[0] for x in list_sinks()]:
        return
    run(["pactl", "load-module", "module-null-sink",
         "sink_name=funkgateway_tx",
         "sink_properties=device.description=FunkGateway_TX"])


def make_rx_sink():
    """Create the virtual RX sink whose monitor receives processed radio audio."""
    if "funkgateway_rx" not in [x[0] for x in list_sinks()]:
        run(["pactl", "load-module", "module-null-sink",
             "sink_name=funkgateway_rx",
             "sink_properties=device.description=FunkGateway_RX"])


def make_rx_source():
    """Expose FunkGateway_RX as a normal capture source for TeamSpeak et al.

    Some clients do not reliably offer *.monitor sources.  The remapped source
    appears as a regular recording device named FunkGateway_RX_Input.
    """
    make_rx_sink()
    if "funkgateway_rx_source" in [x[0] for x in list_sources()]:
        return
    run(["pactl", "load-module", "module-remap-source",
         "master=funkgateway_rx.monitor",
         "source_name=funkgateway_rx_source",
         "source_properties=device.description=FunkGateway_RX_Input"])


class BridgeSignals(QObject):
    level = Signal(int)
    db_level = Signal(float)
    clipping = Signal(int)
    activity = Signal(bool)
    error = Signal(str)


class AudioBridge:
    """Forward FunkGateway_TX.monitor to the radio and detect useful audio."""
    def __init__(self, target_sink, threshold_db=-42, hang_ms=550, tx_gain_db=0):
        self.target_sink=target_sink; self.threshold_db=threshold_db; self.hang_ms=hang_ms
        self.tx_gain_db=float(tx_gain_db)
        self.signals=BridgeSignals(); self.stop_evt=threading.Event(); self.thread=None
        self.last_loud=0.0; self.proc_in=None; self.proc_out=None
        self.output_muted=False

    def set_output_muted(self, muted: bool):
        """Mute normal computer/VoIP -> radio forwarding while keeping detection alive."""
        self.output_muted=bool(muted)

    def start(self):
        self.stop_evt.clear()
        self.thread=threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_evt.set()
        for p in (self.proc_in, self.proc_out):
            if p:
                try: p.terminate()
                except Exception: pass
        if self.thread: self.thread.join(timeout=1)

    def _run(self):
        active=False
        try:
            self.proc_in=subprocess.Popen([
                "parec", "--device=funkgateway_tx.monitor", "--format=s16le",
                "--rate=48000", "--channels=1"], stdout=subprocess.PIPE)
            self.proc_out=subprocess.Popen([
                "pacat", "--playback", f"--device={self.target_sink}",
                "--format=s16le", "--rate=48000", "--channels=1"], stdin=subprocess.PIPE)
            chunk_bytes=4800
            while not self.stop_evt.is_set():
                data=self.proc_in.stdout.read(chunk_bytes)
                if not data: break
                count=len(data)//2
                vals=struct.unpack("<"+"h"*count, data[:count*2])
                clipped=0
                if self.tx_gain_db != 0:
                    factor=10 ** (self.tx_gain_db / 20.0)
                    raw=[int(v*factor) for v in vals]
                    clipped=sum(1 for v in raw if v < -32768 or v > 32767)
                    out_vals=[max(-32768,min(32767,v)) for v in raw]
                    out_data=struct.pack("<"+"h"*count,*out_vals)
                else:
                    out_data=data
                write_data=(b"\x00" * len(out_data)) if self.output_muted else out_data
                self.proc_out.stdin.write(write_data); self.proc_out.stdin.flush()
                rms=math.sqrt(sum(v*v for v in vals)/max(1,count))
                db=20*math.log10(max(rms,1)/32768.0)
                meter=max(0,min(100,int((db+60)*100/60)))
                self.signals.level.emit(meter)
                self.signals.db_level.emit(float(db))
                self.signals.clipping.emit(int(round(clipped*100/max(1,count))))
                now=time.monotonic()
                if db >= self.threshold_db: self.last_loud=now
                wanted=(now-self.last_loud)*1000 <= self.hang_ms
                if wanted != active:
                    active=wanted; self.signals.activity.emit(active)
        except Exception as exc:
            self.signals.error.emit(str(exc))
        finally:
            if active: self.signals.activity.emit(False)


class RxSignals(QObject):
    level = Signal(int)
    db_level = Signal(float)
    activity = Signal(bool)
    error = Signal(str)


class RxActivityDetector:
    """Forward RF audio to FunkGateway_RX and robustly detect a received carrier.

    Detection uses the untouched input samples.  RX gain only affects the copy
    sent to the computer.  Hysteresis, a minimum valid-signal time and hang time
    make the detector resistant to squelch tails, clicks and short level holes.
    """
    def __init__(self, source, threshold_db=-45, hang_ms=500, rx_gain_db=0,
                 hysteresis_db=3, min_active_ms=200):
        self.source=source
        self.threshold_db=float(threshold_db)
        self.hang_ms=int(hang_ms)
        self.rx_gain_db=float(rx_gain_db)
        self.hysteresis_db=max(0.0,float(hysteresis_db))
        self.min_active_ms=max(0,int(min_active_ms))
        self.signals=RxSignals()
        self.stop_evt=threading.Event()
        self.thread=None
        self.proc=None
        self.proc_out=None
        self.output_muted=False

    def set_output_muted(self, muted: bool):
        """Mute only the RF->computer audio copy, not RX detection itself."""
        self.output_muted=bool(muted)

    def start(self):
        make_rx_source()
        self.stop_evt.clear()
        self.thread=threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_evt.set()
        for p in (self.proc, self.proc_out):
            if p:
                try: p.terminate()
                except Exception: pass
        if self.thread:
            self.thread.join(timeout=1)

    def _run(self):
        active=False
        candidate_since=None
        last_keep=0.0
        try:
            self.proc=subprocess.Popen([
                "parec", f"--device={self.source}", "--format=s16le",
                "--rate=48000", "--channels=1"
            ], stdout=subprocess.PIPE)
            self.proc_out=subprocess.Popen([
                "pacat", "--playback", "--device=funkgateway_rx",
                "--format=s16le", "--rate=48000", "--channels=1"
            ], stdin=subprocess.PIPE)
            chunk_bytes=4800
            factor=10 ** (self.rx_gain_db / 20.0)
            off_threshold=self.threshold_db-self.hysteresis_db
            while not self.stop_evt.is_set():
                data=self.proc.stdout.read(chunk_bytes)
                if not data: break
                count=len(data)//2
                vals=struct.unpack("<"+"h"*count, data[:count*2])
                if self.output_muted:
                    out_data=b"\x00" * (count*2)
                elif self.rx_gain_db != 0:
                    out_vals=[max(-32768,min(32767,int(v*factor))) for v in vals]
                    out_data=struct.pack("<"+"h"*count,*out_vals)
                else:
                    out_data=data
                self.proc_out.stdin.write(out_data); self.proc_out.stdin.flush()

                rms=math.sqrt(sum(v*v for v in vals)/max(1,count))
                db=20*math.log10(max(rms,1)/32768.0)
                meter=max(0,min(100,int((db+60)*100/60)))
                self.signals.level.emit(meter)
                self.signals.db_level.emit(float(db))
                now=time.monotonic()

                if not active:
                    if db >= self.threshold_db:
                        if candidate_since is None:
                            candidate_since=now
                        if (now-candidate_since)*1000 >= self.min_active_ms:
                            active=True
                            last_keep=now
                            candidate_since=None
                            self.signals.activity.emit(True)
                    else:
                        candidate_since=None
                else:
                    if db >= off_threshold:
                        last_keep=now
                    if (now-last_keep)*1000 > self.hang_ms:
                        active=False
                        candidate_since=None
                        self.signals.activity.emit(False)
        except Exception as exc:
            self.signals.error.emit(str(exc))
        finally:
            if active:
                self.signals.activity.emit(False)
