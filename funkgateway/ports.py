"""Serial-port discovery for classic and USB PTT interfaces.

Linux uses different device names depending on the hardware:
  /dev/ttyS*    classic/physical serial ports
  /dev/ttyUSB*  USB-to-serial adapters such as FTDI, CP210x or CH34x
  /dev/ttyACM*  USB CDC ACM devices

pyserial normally finds them, but FunkGateway also scans these device patterns
explicitly.  This makes the GUI robust on systems where pyserial's metadata is
incomplete.
"""
from glob import glob

try:
    from serial.tools import list_ports
except Exception:
    list_ports = None


def discover_serial_ports():
    """Return sorted unique device names suitable for the PTT port combo box."""
    found = set()
    if list_ports:
        try:
            found.update(p.device for p in list_ports.comports() if p.device)
        except Exception:
            pass

    for pattern in ("/dev/ttyS*", "/dev/ttyUSB*", "/dev/ttyACM*"):
        found.update(glob(pattern))

    def key(name):
        # Keep classic COM ports first, then USB adapters, then ACM devices.
        rank = 0 if "/ttyS" in name else 1 if "/ttyUSB" in name else 2
        return (rank, name)
    return sorted(found, key=key)


def friendly_port_name(device):
    """Add a plain-language hint without changing the real Linux device path."""
    if "/ttyUSB" in device:
        return f"{device}  – USB-Seriell"
    if "/ttyACM" in device:
        return f"{device}  – USB ACM"
    if "/ttyS" in device:
        return f"{device}  – Serieller Anschluss"
    return device
