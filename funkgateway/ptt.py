"""PTT backends.

All PTT methods implement the same tiny interface: key(True) transmits,
key(False) releases the transmitter.  The GUI therefore does not need to know
whether the user selected a physical COM port, USB serial, CM108 or GPIO.
"""
import subprocess

try:
    import serial
except Exception:
    serial = None


class PTTBase:
    def key(self, on):
        raise NotImplementedError
    def close(self):
        pass


class DryPTT(PTTBase):
    """Safe test backend: shows PTT activity without touching hardware."""
    def key(self, on):
        print("PTT", "ON" if on else "OFF")


class SerialPTT(PTTBase):
    """PTT using RTS or DTR on /dev/ttyS*, /dev/ttyUSB* or /dev/ttyACM*."""
    def __init__(self, port, line="RTS", invert=False):
        if serial is None:
            raise RuntimeError("pyserial ist nicht installiert.")
        self.ser = serial.Serial(port)
        self.line = line
        self.invert = invert
        # Safety first: opening the program must not leave the transmitter keyed.
        self.key(False)

    def key(self, on):
        value = not on if self.invert else on
        if self.line == "RTS":
            self.ser.rts = value
        else:
            self.ser.dtr = value

    def close(self):
        try:
            self.key(False)
            self.ser.close()
        except Exception:
            pass


class CM108PTT(PTTBase):
    """PTT through the external 'cm108' helper and a CM108/CM119 GPIO pin."""
    def __init__(self, dev, gpio=3, invert=False):
        self.dev, self.gpio, self.invert = dev, gpio, invert

    def key(self, on):
        level = int((not on) if self.invert else on)
        subprocess.run(["cm108", "-H", self.dev, "-P", str(self.gpio),
                        "-L", str(level)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class GPIOPTT(PTTBase):
    """PTT using Linux GPIO; supports old and newer python gpiod APIs."""
    def __init__(self, chip, line, invert=False):
        import gpiod
        self.invert = invert
        self.line_no = line
        if hasattr(gpiod, "request_lines"):
            from gpiod.line import Direction, Value
            self.Value = Value
            self.req = gpiod.request_lines(
                chip, consumer="funkgateway-ui",
                config={line: gpiod.LineSettings(direction=Direction.OUTPUT,
                        output_value=Value.INACTIVE)})
            self.old = False
        else:
            self.chip = gpiod.Chip(chip)
            self.line = self.chip.get_line(line)
            self.line.request(consumer="funkgateway-ui", type=gpiod.LINE_REQ_DIR_OUT)
            self.req = None
            self.old = True

    def key(self, on):
        value = not on if self.invert else on
        if self.req:
            self.req.set_value(self.line_no,
                self.Value.ACTIVE if value else self.Value.INACTIVE)
        else:
            self.line.set_value(int(value))

    def close(self):
        try:
            self.key(False)
            if self.req:
                self.req.release()
            else:
                self.line.release(); self.chip.close()
        except Exception:
            pass
