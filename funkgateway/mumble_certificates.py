from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from .constants import CFG_DIR

CERT_DIR = CFG_DIR / "mumble_certificates"


def ensure_cert_dir():
    CERT_DIR.mkdir(parents=True, exist_ok=True)


def _crypto():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    return x509, hashes, serialization, rsa, NameOID


def _safe(name):
    cleaned="".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(name or "").strip())
    return cleaned.strip("._") or "mumble"


def create_certificate(name):
    ensure_cert_dir()
    x509,hashes,serialization,rsa,NameOID=_crypto()
    safe=_safe(name)
    cert_path=CERT_DIR/f"{safe}.cert.pem"
    key_path=CERT_DIR/f"{safe}.key.pem"
    if cert_path.exists() or key_path.exists():
        raise RuntimeError("Ein Zertifikat mit diesem Namen existiert bereits.")
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,str(name or "FunkGateway Linux"))])
    now=datetime.now(timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
          .public_key(key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=3650))
          .sign(key,hashes.SHA256()))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return certificate_info(cert_path,key_path)


def certificate_info(cert_path,key_path=None):
    x509,hashes,_serialization,_rsa,_NameOID=_crypto()
    cert_path=Path(cert_path)
    cert=x509.load_pem_x509_certificate(cert_path.read_bytes())
    if key_path is None:
        key_path=cert_path.with_name(cert_path.name.replace(".cert.pem",".key.pem"))
    key_path=Path(key_path)
    return {
        "id":cert_path.name.removesuffix(".cert.pem"),
        "name":cert_path.name.removesuffix(".cert.pem"),
        "cert_path":str(cert_path),
        "key_path":str(key_path) if key_path.exists() else "",
        "subject":cert.subject.rfc4514_string(),
        "fingerprint":cert.fingerprint(hashes.SHA256()).hex(":").upper(),
    }


def list_certificates():
    ensure_cert_dir()
    rows=[]
    for path in sorted(CERT_DIR.glob("*.cert.pem"),key=lambda p:p.name.casefold()):
        try:
            info=certificate_info(path)
            if info["key_path"]:
                rows.append(info)
        except Exception:
            pass
    return rows
