"""PulseAudio/PipeWire routing and audio-triggered PTT/RX detection."""
import math, struct, subprocess, threading, time
from collections import deque
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
    dtmf = Signal(str)
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

        # DTMF detector.  When tone suppression is enabled, RF->VoIP audio is
        # delayed by a short look-ahead so the first part of a DTMF tone can be
        # removed before it reaches TeamSpeak/Mumble.
        self.dtmf_enabled=False
        self.dtmf_suppress_tones=True
        self.dtmf_lookahead_ms=200
        self._dtmf_candidate=None
        self._dtmf_candidate_count=0
        self._dtmf_active=None
        self._dtmf_release_count=0

    def configure_dtmf(self, enabled: bool, suppress_tones: bool=True, lookahead_ms: int=200):
        self.dtmf_enabled=bool(enabled)
        self.dtmf_suppress_tones=bool(suppress_tones)
        self.dtmf_lookahead_ms=max(100,min(500,int(lookahead_ms)))

    @staticmethod
    def _goertzel_power(samples, freq, sample_rate=48000):
        """Goertzel energy at the exact requested frequency.

        0.5.9.0 rounded each DTMF frequency to the nearest DFT bin.  With our
        50 ms blocks that means 20 Hz steps (e.g. 770 -> 760 and 1209 -> 1200).
        Some hand microphones/DTMF generators therefore fell just outside the
        detector margin, especially the digit 4 (770 + 1209 Hz).
        """
        if not samples:
            return 0.0
        omega=2.0*math.pi*float(freq)/float(sample_rate)
        coeff=2.0*math.cos(omega)
        q1=q2=0.0
        for x in samples:
            q0=float(x)+coeff*q1-q2
            q2=q1
            q1=q0
        return max(0.0,q1*q1+q2*q2-coeff*q1*q2)

    def _detect_dtmf_digit(self, samples):
        """Return one DTMF symbol for a confident 50 ms block, otherwise None."""
        if not self.dtmf_enabled or len(samples) < 400:
            return None

        total=sum(float(v)*float(v) for v in samples)
        if total <= 1.0:
            return None
        rms=math.sqrt(total/len(samples))
        # Avoid classifying quiet background/squelch noise as DTMF.
        if rms < 220.0:
            return None

        rows=(697,770,852,941)
        cols=(1209,1336,1477,1633)
        keypad=(
            ("1","2","3","A"),
            ("4","5","6","B"),
            ("7","8","9","C"),
            ("*","0","#","D"),
        )
        rp=[self._goertzel_power(samples,f) for f in rows]
        cp=[self._goertzel_power(samples,f) for f in cols]
        ri=max(range(4), key=lambda i:rp[i])
        ci=max(range(4), key=lambda i:cp[i])
        rbest=rp[ri]; cbest=cp[ci]
        rsecond=sorted(rp)[-2] if len(rp)>1 else 0.0
        csecond=sorted(cp)[-2] if len(cp)>1 else 0.0

        # Dominant row/column plus reasonable two-tone energy and twist.
        # RF audio, microphone frequency response and deviation can make one
        # DTMF component noticeably weaker.  Keep the detector selective, but
        # allow more real-world margin than 0.5.9.0.
        if rbest < max(1.0,rsecond)*2.0 or cbest < max(1.0,csecond)*2.0:
            return None
        n=float(len(samples))
        fraction=(rbest+cbest)/(max(1.0,n*total))
        if fraction < 0.10:
            return None
        twist=rbest/max(1.0,cbest)
        if not (0.10 <= twist <= 10.0):
            return None
        return keypad[ri][ci]

    def _dtmf_block_state(self, samples):
        digit=self._detect_dtmf_digit(samples)
        if digit:
            if digit == self._dtmf_candidate:
                self._dtmf_candidate_count += 1
            else:
                self._dtmf_candidate=digit
                self._dtmf_candidate_count=1
            self._dtmf_release_count=0
            if self._dtmf_candidate_count >= 2 and self._dtmf_active != digit:
                self._dtmf_active=digit
                self.signals.dtmf.emit(digit)
            return digit, True

        self._dtmf_candidate=None
        self._dtmf_candidate_count=0
        if self._dtmf_active is not None:
            self._dtmf_release_count += 1
            if self._dtmf_release_count >= 2:
                self._dtmf_active=None
                self._dtmf_release_count=0
            return None, True
        return None, False

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
            chunk_bytes=4800  # 50 ms @ 48 kHz / 16-bit mono
            factor=10 ** (self.rx_gain_db / 20.0)
            off_threshold=self.threshold_db-self.hysteresis_db
            delayed=deque()
            while not self.stop_evt.is_set():
                data=self.proc.stdout.read(chunk_bytes)
                if not data: break
                count=len(data)//2
                vals=struct.unpack("<"+"h"*count, data[:count*2])

                if self.rx_gain_db != 0:
                    out_vals=[max(-32768,min(32767,int(v*factor))) for v in vals]
                    out_data=struct.pack("<"+"h"*count,*out_vals)
                else:
                    out_data=data

                _digit, tone_suspect=self._dtmf_block_state(vals)

                if self.dtmf_enabled and self.dtmf_suppress_tones:
                    # Keep enough unplayed audio to erase the beginning of a
                    # newly recognized DTMF tone before it reaches VoIP.
                    delay_chunks=max(2,int(math.ceil(self.dtmf_lookahead_ms/50.0)))
                    if tone_suspect:
                        # Any audio still waiting in the look-ahead buffer may
                        # contain the beginning of this DTMF tone.
                        delayed=deque((chunk,True) for chunk,_mute in delayed)
                    delayed.append((out_data,bool(tone_suspect)))
                    if len(delayed) > delay_chunks:
                        play, tone_mute=delayed.popleft()
                        if self.output_muted or tone_mute:
                            play=b"\x00"*len(play)
                        self.proc_out.stdin.write(play); self.proc_out.stdin.flush()
                else:
                    play=(b"\x00"*len(out_data)) if self.output_muted else out_data
                    self.proc_out.stdin.write(play); self.proc_out.stdin.flush()

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