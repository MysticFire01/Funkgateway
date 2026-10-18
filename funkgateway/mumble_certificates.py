from __future__ import annotations

import hashlib
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .constants import CFG_DIR


CERT_DIR = CFG_DIR / "mumble_certificates"


def ensure_cert_dir():
    CERT_DIR.mkdir(parents=True, exist_ok=True)


def _safe_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in str(name or "").strip())
    return cleaned.strip("._") or "mumble"


def _load_crypto():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
    return x509, hashes, serialization, rsa, pkcs12, NameOID


def certificate_backend_status():
    """Exercise the exact cryptography pieces used by certificate creation.

    This is intentionally in-memory: no user certificate files are created.
    """
    try:
        x509, hashes, serialization, rsa, pkcs12, NameOID = _load_crypto()
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "FunkGateway Mumble Test"),
        ])
        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .sign(key, hashes.SHA256())
        )
        pem = cert.public_bytes(serialization.Encoding.PEM)
        parsed = x509.load_pem_x509_certificate(pem)
        fingerprint = parsed.fingerprint(hashes.SHA256()).hex(":").upper()
        return {
            "ok": True,
            "version": __import__("cryptography").__version__,
            "fingerprint": fingerprint,
        }
    except Exception as exc:
        return {
            "ok": False,
            "version": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def _protect_key(key_path):
    """Private Mumble identity files should not be world-readable on Linux."""
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass


def _paths(base: str):
    safe = _safe_name(base)
    return CERT_DIR / f"{safe}.cert.pem", CERT_DIR / f"{safe}.key.pem"


def create_certificate(name: str):
    ensure_cert_dir()
    x509, hashes, serialization, rsa, _pkcs12, NameOID = _load_crypto()
    cert_path, key_path = _paths(name)
    if cert_path.exists() or key_path.exists():
        raise RuntimeError("Ein Zertifikat mit diesem Namen existiert bereits.")

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, str(name or "FunkGateway Mumble")),
    ])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _protect_key(key_path)
    return certificate_info(cert_path, key_path)


def import_pkcs12(path: str | Path, password: str | None, name: str | None = None):
    ensure_cert_dir()
    x509, _hashes, serialization, _rsa, pkcs12, _NameOID = _load_crypto()
    src = Path(path)
    data = src.read_bytes()
    pwd = password.encode("utf-8") if password else None
    key, cert, _extra = pkcs12.load_key_and_certificates(data, pwd)
    if key is None or cert is None:
        raise RuntimeError("P12/PFX enthält kein verwendbares Zertifikat mit privatem Schlüssel.")

    base = name or src.stem
    cert_path, key_path = _paths(base)
    if cert_path.exists() or key_path.exists():
        raise RuntimeError("Ein Zertifikat mit diesem Namen existiert bereits.")

    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return certificate_info(cert_path, key_path)


def import_pem(cert_file: str | Path, key_file: str | Path, name: str | None = None):
    ensure_cert_dir()
    x509, _hashes, serialization, _rsa, _pkcs12, _NameOID = _load_crypto()
    cert_src, key_src = Path(cert_file), Path(key_file)
    cert = x509.load_pem_x509_certificate(cert_src.read_bytes())
    key = serialization.load_pem_private_key(key_src.read_bytes(), password=None)

    # Validate that certificate and private key belong together.
    cert_pub = cert.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key_pub = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if cert_pub != key_pub:
        raise RuntimeError("Zertifikat und privater Schlüssel gehören nicht zusammen.")

    base = name or cert_src.stem.replace(".cert", "")
    cert_path, key_path = _paths(base)
    if cert_path.exists() or key_path.exists():
        raise RuntimeError("Ein Zertifikat mit diesem Namen existiert bereits.")
    shutil.copy2(cert_src, cert_path)
    shutil.copy2(key_src, key_path)
    _protect_key(key_path)
    return certificate_info(cert_path, key_path)


def certificate_info(cert_path: str | Path, key_path: str | Path | None = None):
    x509, hashes, _serialization, _rsa, _pkcs12, _NameOID = _load_crypto()
    cert_path = Path(cert_path)
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    if key_path is None:
        candidate = cert_path.with_name(cert_path.name.replace(".cert.pem", ".key.pem"))
        key_path = candidate if candidate.exists() else None
    key_path = Path(key_path) if key_path else None

    cn = ""
    try:
        cn = cert.subject.rfc4514_string()
    except Exception:
        pass

    return {
        "id": cert_path.name.removesuffix(".cert.pem"),
        "name": cert_path.name.removesuffix(".cert.pem"),
        "cert_path": str(cert_path),
        "key_path": str(key_path) if key_path and key_path.exists() else "",
        "subject": cn,
        "fingerprint": cert.fingerprint(hashes.SHA256()).hex(":").upper(),
        "not_after": getattr(cert, "not_valid_after_utc", cert.not_valid_after).isoformat(),
    }


def list_certificates():
    ensure_cert_dir()
    result = []
    for cert in sorted(CERT_DIR.glob("*.cert.pem"), key=lambda p: p.name.casefold()):
        try:
            info = certificate_info(cert)
            if info["key_path"]:
                result.append(info)
        except Exception:
            continue
    return result


def delete_certificate(cert_id: str):
    cert_path, key_path = _paths(cert_id)
    for path in (cert_path, key_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def export_pem(cert_id: str, destination_dir: str | Path):
    """Export the selected certificate and private key as a PEM pair."""
    ensure_cert_dir()
    cert_path, key_path = _paths(cert_id)
    if not cert_path.exists() or not key_path.exists():
        raise RuntimeError("Zertifikat oder privater Schlüssel wurde nicht gefunden.")

    dest = Path(destination_dir)
    dest.mkdir(parents=True, exist_ok=True)
    out_cert = dest / cert_path.name
    out_key = dest / key_path.name

    copied = []
    for src, dst in ((cert_path, out_cert), (key_path, out_key)):
        try:
            if src.resolve() == dst.resolve():
                continue
        except Exception:
            pass
        shutil.copy2(src, dst)
        if src == key_path:
            _protect_key(dst)
        copied.append(str(dst))

    return {
        "cert_path": str(out_cert),
        "key_path": str(out_key),
        "copied": copied,
    }


def export_pkcs12(
    cert_id: str,
    destination_dir: str | Path,
    password: str | None = None,
):
    """Export the selected identity as a single PKCS#12/PFX file."""
    ensure_cert_dir()
    cert_path, key_path = _paths(cert_id)
    if not cert_path.exists() or not key_path.exists():
        raise RuntimeError("Zertifikat oder privater Schlüssel wurde nicht gefunden.")

    x509, _hashes, serialization, _rsa, pkcs12, _NameOID = _load_crypto()
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    key = serialization.load_pem_private_key(
        key_path.read_bytes(),
        password=None,
    )

    if password:
        encryption = serialization.BestAvailableEncryption(
            password.encode("utf-8")
        )
    else:
        encryption = serialization.NoEncryption()

    data = pkcs12.serialize_key_and_certificates(
        name=str(cert_id).encode("utf-8"),
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=encryption,
    )

    dest = Path(destination_dir)
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"{_safe_name(cert_id)}.p12"
    out.write_bytes(data)
    _protect_key(out)
    return str(out)
