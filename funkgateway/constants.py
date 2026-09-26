"""Shared application names and paths.

Keeping paths in one place makes the rest of the source easier to read.
"""
from pathlib import Path

APP_NAME = "FunkGateway UI"
VERSION = "0.5.9.44"
CFG_DIR = Path.home() / ".config" / "funkgateway-ui"
CFG_FILE = CFG_DIR / "config.json"
LOG_FILE = CFG_DIR / "gateway.log"
CW_FILE = CFG_DIR / "cw-id.wav"
DTMF_FILE = CFG_DIR / "dtmf.wav"
ID_RECORDING_FILE = CFG_DIR / "rufzeichen.wav"
ROGER_FILE = CFG_DIR / "rogerbeep.wav"
DEFAULT_WAV_DIR = Path(__file__).resolve().parents[1] / "default_wavs"


def ensure_cfg():
    """Create the per-user configuration directory if necessary."""
    CFG_DIR.mkdir(parents=True, exist_ok=True)
