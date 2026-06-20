"""
ssl_cert.py — Self-signed TLS certificate for CloudinatorFTP WebDAV HTTPS
--------------------------------------------------------------------------
Generates a self-signed certificate stored in db/ alongside the other
server keys.  The cert is a proper CA cert so it can be imported into
Windows/macOS/Linux as a Trusted Root, making HTTPS WebDAV work without
any registry changes.

Why HTTPS over HTTP for WebDAV:
  • Windows maps HTTPS WebDAV drives with zero registry edits
  • BasicAuthLevel registry key NOT needed
  • Credentials are encrypted in transit

One-time Windows setup after cert is generated:
  1. Copy  db/webdav.crt  to the Windows machine
  2. Run in elevated PowerShell:
       Import-Certificate -FilePath "webdav.crt" `
           -CertStoreLocation Cert:\\LocalMachine\\Root
  3. Map drive:
       net use X: https://SERVER-IP:8443/ /user:admin admin123 /persistent:yes
  That's it — no registry edit, no WebClient config needed.

macOS:
  sudo security add-trusted-cert -d -r trustRoot \
      -k /Library/Keychains/System.keychain webdav.crt

Linux (davfs2):
  sudo cp webdav.crt /usr/local/share/ca-certificates/cloudinator.crt
  sudo update-ca-certificates
  sudo mount -t davfs https://SERVER-IP:8443/ /mnt/cloudinator
"""

import datetime
import ipaddress
import os
import socket

# ── IP discovery ──────────────────────────────────────────────────────────


def _local_ips() -> set:
    """Collect all local IPv4 addresses to embed as Subject Alternative Names."""
    ips: set = {"127.0.0.1"}
    # Primary outbound IP (the one used to reach the internet / LAN gateway)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    # Hostname-resolved IPs
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            addr = info[4][0]
            if ":" not in addr:  # skip IPv6
                ips.add(addr)
    except Exception:
        pass
    return ips


# ── Certificate generation ────────────────────────────────────────────────


def _generate(cert_path: str, key_path: str):
    """Create a self-signed RSA-2048 certificate valid for 10 years."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    # ── Private key ───────────────────────────────────────────────────────
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # ── Subject / Issuer (self-signed → same) ─────────────────────────────
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "CloudinatorFTP"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CloudinatorFTP"),
        ]
    )

    # ── Subject Alternative Names ─────────────────────────────────────────
    # Modern TLS clients ignore CN and check SANs only.
    # We embed every local IP + localhost so the cert matches regardless of
    # which IP the client uses to reach this server.
    san: list = [x509.DNSName("localhost")]
    for ip_str in sorted(_local_ips()):
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(ip_str)))
        except ValueError:
            pass

    now = datetime.datetime.utcnow()

    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=3650))  # 10 years
        # CA flag: lets Windows import it as a Trusted Root CA
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.SubjectAlternativeName(san),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    # ── Write files ───────────────────────────────────────────────────────
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    with open(key_path, "wb") as f:
        f.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )

    ips_listed = ", ".join(str(e.value) for e in san if isinstance(e, x509.IPAddress))
    print(f"🔐 WebDAV TLS cert generated: {cert_path}")
    print(f"   SANs: localhost, {ips_listed}")
    print(f"   Valid for 10 years")


# ── Public API ────────────────────────────────────────────────────────────


def get_cert_paths(db_dir: str) -> tuple[str, str]:
    """Return (cert_path, key_path), generating the pair if it doesn't exist."""
    cert_path = os.path.join(db_dir, "webdav.crt")
    key_path = os.path.join(db_dir, "webdav.key")
    if not (os.path.exists(cert_path) and os.path.exists(key_path)):
        _generate(cert_path, key_path)
    return cert_path, key_path


def regenerate(db_dir: str) -> tuple[str, str]:
    """
    Force-regenerate the certificate (e.g. after an IP change).
    Call this when you add a new network interface or change the server IP
    and clients start seeing hostname-mismatch errors.
    After regenerating, re-import webdav.crt on every client machine.
    """
    cert_path = os.path.join(db_dir, "webdav.crt")
    key_path = os.path.join(db_dir, "webdav.key")
    for p in (cert_path, key_path):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    _generate(cert_path, key_path)
    print("⚠️  Re-import webdav.crt on every client machine that mapped a drive.")
    return cert_path, key_path


# ── CLI helper ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.dirname(__file__))
    from paths import get_db_dir

    db = get_db_dir(create=True)

    if "--regenerate" in sys.argv:
        regenerate(db)
    else:
        cert, key = get_cert_paths(db)
        print(f"Certificate : {cert}")
        print(f"Private key : {key}")
        print()
        print("Windows — import as Trusted Root CA (elevated PowerShell):")
        print(
            f'  Import-Certificate -FilePath "{cert}" -CertStoreLocation Cert:\\LocalMachine\\Root'
        )
        print()
        print("Then map the drive (no registry edit needed):")
        from config import WEBDAV_HTTPS_PORT

        for ip in sorted(_local_ips()):
            print(
                f"  net use X: https://{ip}:{WEBDAV_HTTPS_PORT}/ /user:admin PASSWORD /persistent:yes"
            )
