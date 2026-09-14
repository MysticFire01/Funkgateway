"""Small WAV generators for CW and DTMF identification/control tones."""
import math, struct, wave
from .constants import ensure_cfg

MORSE={"A":".-","B":"-...","C":"-.-.","D":"-..","E":".","F":"..-.","G":"--.","H":"....","I":"..","J":".---","K":"-.-","L":".-..","M":"--","N":"-.","O":"---","P":".--.","Q":"--.-","R":".-.","S":"...","T":"-","U":"..-","V":"...-","W":".--","X":"-..-","Y":"-.--","Z":"--..","0":"-----","1":".----","2":"..---","3":"...--","4":"....-","5":".....","6":"-....","7":"--...","8":"---..","9":"----.","/":"-..-.","-":"-....-"}
DTMF={"1":(697,1209),"2":(697,1336),"3":(697,1477),"A":(697,1633),"4":(770,1209),"5":(770,1336),"6":(770,1477),"B":(770,1633),"7":(852,1209),"8":(852,1336),"9":(852,1477),"C":(852,1633),"*":(941,1209),"0":(941,1336),"#":(941,1477),"D":(941,1633)}

def write_wav(path,samples,rate=48000):
    ensure_cfg()
    with wave.open(str(path),"wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        vals=[max(-32768,min(32767,int(v))) for v in samples]
        w.writeframes(struct.pack("<"+"h"*len(vals),*vals))

def make_cw(text,path,wpm=18,freq=700,rate=48000,amplitude=10000):
    dot=1.2/max(5,wpm); samples=[]
    def tone(sec):
        for i in range(int(rate*sec)): samples.append(int(amplitude*math.sin(2*math.pi*freq*i/rate)))
    def silence(sec): samples.extend([0]*int(rate*sec))
    words=text.upper().split()
    for wi,word in enumerate(words):
        for ci,ch in enumerate(word):
            code=MORSE.get(ch)
            if not code: continue
            for si,sym in enumerate(code):
                tone(dot if sym=="." else dot*3)
                if si<len(code)-1: silence(dot)
            if ci<len(word)-1: silence(dot*3)
        if wi<len(words)-1: silence(dot*7)
    if not samples: raise RuntimeError("Kein gültiger CW-Text.")
    write_wav(path,samples,rate)

def make_dtmf(text,path,rate=48000,digit_ms=160,pause_ms=70):
    samples=[]
    for ch in text.upper():
        if ch not in DTMF: continue
        f1,f2=DTMF[ch]
        for i in range(int(rate*digit_ms/1000)):
            samples.append(int(6500*math.sin(2*math.pi*f1*i/rate)+6500*math.sin(2*math.pi*f2*i/rate)))
        samples.extend([0]*int(rate*pause_ms/1000))
    if not samples: raise RuntimeError("Keine gültigen DTMF-Zeichen.")
    write_wav(path,samples,rate)


def make_roger_tone(path, kind="single", freq=800, rate=48000, amplitude=10000):
    """Create a short selectable Roger tone WAV.

    kind='single' -> one 120 ms tone
    kind='double' -> two 80 ms tones with an 80 ms pause
    """
    samples=[]
    def tone(sec, f=freq):
        start=len(samples)
        for i in range(int(rate*sec)):
            # tiny 5 ms fade-in/out to avoid clicks
            n=int(rate*sec)
            edge=max(1,int(rate*0.005))
            gain=1.0
            if i < edge: gain=i/edge
            elif i >= n-edge: gain=(n-i-1)/edge
            samples.append(int(amplitude*gain*math.sin(2*math.pi*f*i/rate)))
    def silence(sec):
        samples.extend([0]*int(rate*sec))
    if kind == "single":
        tone(0.12)
    elif kind == "double":
        tone(0.08); silence(0.08); tone(0.08)
    else:
        raise RuntimeError("Unbekannter Rogerbeep-Typ.")
    write_wav(path,samples,rate)
